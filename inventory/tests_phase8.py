from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership

from .models import Block, Plot, PlotHold, PlotStatusHistory
from .services import hold_plot


class Phase8InventoryTests(TransactionTestCase):
    """Phase 8: concurrency, expiry and inventory RBAC acceptance tests."""

    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.manager_user = user_model.objects.create_user(username="phase8-manager", password="test-pass")
        self.executive_user = user_model.objects.create_user(username="phase8-executive", password="test-pass")
        self.telecaller_user = user_model.objects.create_user(username="phase8-telecaller", password="test-pass")
        self.organization = Organization.objects.create(name="Phase 8 CRM", slug="phase8-crm")
        self.manager = OrganizationMembership.objects.create(
            organization=self.organization, user=self.manager_user, role=OrganizationMembership.Role.MANAGER
        )
        self.executive = OrganizationMembership.objects.create(
            organization=self.organization, user=self.executive_user, role="site_visit_exec"
        )
        self.telecaller = OrganizationMembership.objects.create(
            organization=self.organization, user=self.telecaller_user, role=OrganizationMembership.Role.TELECALLER
        )
        self.block = Block.objects.create(organization=self.organization, name="Phase 8 Block", code="P8")
        self.plot = Plot.objects.create(
            organization=self.organization, block=self.block, plot_number="P8-001",
            size=Decimal("100"),
        )

    def test_fr_p8_07_site_visit_executive_can_request_hold_but_not_block(self):
        client = APIClient()
        client.force_authenticate(self.executive_user)
        hold_url = reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id])
        block_url = reverse("inventory:plot-block", args=[self.organization.slug, self.plot.id])

        hold_response = client.post(hold_url, {"reason": "Temporary customer request"}, format="json", HTTP_X_IDEMPOTENCY_KEY="p8-hold-1")
        self.assertEqual(hold_response.status_code, 200, hold_response.data)

        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.HOLD)
        self.assertEqual(client.post(block_url, {"reason": "Permanent block"}, format="json").status_code, 403)

    def test_plot_hold_idempotency_replays_and_rejects_payload_conflict(self):
        client = APIClient(); client.force_authenticate(self.manager_user)
        url = reverse("inventory:plot-hold", args=[self.organization.slug, self.plot.id])
        first = client.post(url, {"reason": "Customer request"}, format="json", HTTP_X_IDEMPOTENCY_KEY="p8-hold-replay")
        self.assertEqual(first.status_code, 200, first.data)
        second = client.post(url, {"reason": "Customer request"}, format="json", HTTP_X_IDEMPOTENCY_KEY="p8-hold-replay")
        self.assertEqual(second.status_code, 200, second.data)
        conflict = client.post(url, {"reason": "Different request"}, format="json", HTTP_X_IDEMPOTENCY_KEY="p8-hold-replay")
        self.assertEqual(conflict.status_code, 409, conflict.data)

    def test_fr_p8_04_expired_holds_return_to_available_with_history(self):
        expired_at = timezone.now() - timedelta(minutes=1)
        PlotHold.objects.create(
            plot=self.plot,
            action_type=PlotHold.ActionType.HOLD,
            reason="Expired customer hold",
            to_datetime=expired_at,
            created_by=self.manager_user,
        )
        self.plot.status = Plot.Status.HOLD
        self.plot.save(update_fields=["status", "updated_at"])

        from .services import expire_plot_holds
        expired_count = expire_plot_holds(now=timezone.now())

        self.assertEqual(expired_count, 1)
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.AVAILABLE)
        self.assertTrue(PlotHold.objects.get(plot=self.plot).released_at)
        self.assertTrue(PlotStatusHistory.objects.filter(plot=self.plot, new_status=Plot.Status.AVAILABLE).exists())

    def test_nfr_p8_01_fifty_parallel_holds_have_exactly_one_winner(self):
        def attempt(_index):
            close_old_connections()
            try:
                plot = Plot.objects.get(pk=self.plot.id)
                hold_plot(plot=plot, reason="Parallel request", user=self.manager_user)
                return "success"
            except Exception as error:  # database lock races are rejected outcomes
                return type(error).__name__
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=50) as executor:
            results = list(executor.map(attempt, range(50)))

        self.assertEqual(results.count("success"), 1)
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.HOLD)
        self.assertEqual(PlotStatusHistory.objects.filter(plot=self.plot).count(), 1)
