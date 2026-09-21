from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership

from .models import Block, Plot, PlotHold, PlotStatusHistory


class PlotStatusLifecycleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="manager@example.com", email="manager@example.com", password="password123")
        self.telecaller = user_model.objects.create_user(username="viewer@example.com", email="viewer@example.com", password="password123")
        self.other_user = user_model.objects.create_user(username="other@example.com", email="other@example.com", password="password123")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=self.other_organization, user=self.other_user, role=OrganizationMembership.Role.MANAGER)
        self.block = Block.objects.create(organization=self.organization, name="A Block", code="A")
        self.other_block = Block.objects.create(organization=self.other_organization, name="Foreign Block", code="F")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def plot(self, status=Plot.Status.AVAILABLE, number="A-101"):
        return Plot.objects.create(
            organization=self.organization, block=self.block,
            plot_number=number, size=Decimal("120.00"), status=status,
        )

    def other_plot(self):
        return Plot.objects.create(
            organization=self.other_organization, block=self.other_block,
            plot_number="F-101", size=Decimal("120.00"),
        )

    def operation_url(self, plot, operation):
        return reverse(f"inventory:plot-{operation}", args=[self.organization.slug, plot.id])

    def status_url(self, plot):
        return self.operation_url(plot, "status")

    def status_payload(self, new_status, reason="Lifecycle reason"):
        return {"status": new_status, "reason": reason}

    def test_all_supported_transitions(self):
        transitions = {
            Plot.Status.AVAILABLE: [Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED, Plot.Status.UNDER_CONSTRUCTION],
            Plot.Status.BLOCKED: [Plot.Status.AVAILABLE, Plot.Status.HOLD],
            Plot.Status.HOLD: [Plot.Status.AVAILABLE, Plot.Status.BOOKED],
            Plot.Status.BOOKED: [Plot.Status.SOLD, Plot.Status.CANCELLED],
            Plot.Status.SOLD: [Plot.Status.CANCELLED],
            Plot.Status.CANCELLED: [Plot.Status.AVAILABLE],
            Plot.Status.UNDER_CONSTRUCTION: [Plot.Status.AVAILABLE, Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED],
        }
        sequence = 0
        for old_status, targets in transitions.items():
            for new_status in targets:
                sequence += 1
                plot = self.plot(old_status, f"A-{sequence}")
                response = self.client.post(self.status_url(plot), self.status_payload(new_status), format="json")
                self.assertEqual(response.status_code, 200, response.data)
                plot.refresh_from_db()
                self.assertEqual(plot.status, new_status)
                self.assertTrue(PlotStatusHistory.objects.filter(plot=plot, old_status=old_status, new_status=new_status).exists())

    def test_invalid_and_same_status_transitions_are_rejected_without_history(self):
        for old_status, new_status in [
            (Plot.Status.AVAILABLE, Plot.Status.SOLD),
            (Plot.Status.AVAILABLE, Plot.Status.CANCELLED),
            (Plot.Status.SOLD, Plot.Status.BOOKED),
            (Plot.Status.SOLD, Plot.Status.AVAILABLE),
            (Plot.Status.BOOKED, Plot.Status.AVAILABLE),
            (Plot.Status.AVAILABLE, Plot.Status.AVAILABLE),
        ]:
            plot = self.plot(old_status, f"A-{old_status}-{new_status}")
            response = self.client.post(self.status_url(plot), self.status_payload(new_status), format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(PlotStatusHistory.objects.filter(plot=plot).count(), 0)

    def test_reason_is_required_for_block_hold_and_cancel(self):
        available = self.plot(number="A-reason-1")
        self.assertEqual(self.client.post(self.status_url(available), {"status": "blocked"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.status_url(available), {"status": "hold"}, format="json").status_code, 400)
        booked = self.plot(Plot.Status.BOOKED, "A-reason-2")
        self.assertEqual(self.client.post(self.status_url(booked), {"status": "cancelled"}, format="json").status_code, 400)

    def test_history_is_immutable_and_history_api_is_newest_first(self):
        plot = self.plot()
        self.client.post(self.status_url(plot), self.status_payload("blocked", "Initial block"), format="json")
        self.client.post(self.status_url(plot), self.status_payload("available", "Released"), format="json")
        history = list(PlotStatusHistory.objects.filter(plot=plot).order_by("changed_at", "id"))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].reason, "Initial block")
        history[0].reason = "Changed"
        with self.assertRaises(ValidationError):
            history[0].save()
        response = self.client.get(reverse("inventory:plot-history", args=[self.organization.slug, plot.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["new_status"], Plot.Status.AVAILABLE)

    def test_block_hold_and_release_create_and_preserve_hold_records(self):
        plot = self.plot()
        response = self.client.post(self.operation_url(plot, "block"), {"reason": "Customer request"}, format="json")
        self.assertEqual(response.status_code, 200)
        record = PlotHold.objects.get(plot=plot)
        self.assertEqual(record.action_type, PlotHold.ActionType.BLOCK)
        response = self.client.post(self.operation_url(plot, "release"), {"reason": "Request withdrawn"}, format="json")
        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertIsNotNone(record.released_at)
        self.assertEqual(PlotHold.objects.filter(plot=plot).count(), 1)

        response = self.client.post(self.operation_url(plot, "hold"), {"reason": "Customer hold"}, format="json", HTTP_X_IDEMPOTENCY_KEY="p3-hold-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlotHold.objects.filter(plot=plot, action_type=PlotHold.ActionType.HOLD).count(), 1)

    def test_invalid_block_hold_and_release_are_rejected(self):
        booked = self.plot(Plot.Status.BOOKED, "A-booked")
        self.assertEqual(self.client.post(self.operation_url(booked, "block"), {"reason": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.operation_url(booked, "hold"), {"reason": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.operation_url(booked, "release"), {"reason": "x"}, format="json").status_code, 400)

    def test_hold_range_and_overlap_rules(self):
        plot = self.plot()
        now = timezone.now()
        PlotHold.objects.create(
            plot=plot, action_type=PlotHold.ActionType.HOLD, reason="Existing",
            from_datetime=now, to_datetime=now + timedelta(hours=2), created_by=self.user,
        )
        payload = {
            "reason": "New", "from_datetime": (now + timedelta(hours=1)).isoformat(),
            "to_datetime": (now + timedelta(hours=3)).isoformat(),
        }
        self.assertEqual(self.client.post(self.operation_url(plot, "hold"), payload, format="json", HTTP_X_IDEMPOTENCY_KEY="p3-overlap-1").status_code, 400)
        PlotHold.objects.filter(plot=plot).update(released_at=timezone.now())
        payload["from_datetime"] = (now + timedelta(hours=3)).isoformat()
        payload["to_datetime"] = (now + timedelta(hours=4)).isoformat()
        self.assertEqual(self.client.post(self.operation_url(plot, "hold"), payload, format="json", HTTP_X_IDEMPOTENCY_KEY="p3-overlap-2").status_code, 200)
        invalid_range = {"reason": "Invalid", "from_datetime": (now + timedelta(hours=5)).isoformat(), "to_datetime": (now + timedelta(hours=4)).isoformat()}
        released_plot = self.plot(number="A-range")
        self.assertEqual(self.client.post(self.operation_url(released_plot, "hold"), invalid_range, format="json").status_code, 400)

    def test_bulk_is_all_or_nothing_and_creates_per_plot_history(self):
        first = self.plot(number="A-bulk-1")
        second = self.plot(number="A-bulk-2")
        bulk_url = reverse("inventory:plot-bulk-status", args=[self.organization.slug])
        response = self.client.post(bulk_url, {"plot_ids": [first.id, second.id], "status": "blocked", "reason": "Project hold"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(PlotStatusHistory.objects.filter(plot__in=[first, second]).count(), 2)

        invalid = self.plot(Plot.Status.SOLD, "A-bulk-sold")
        available = self.plot(number="A-bulk-available")
        response = self.client.post(bulk_url, {"plot_ids": [available.id, invalid.id], "status": "blocked", "reason": "Project hold"}, format="json")
        self.assertEqual(response.status_code, 400)
        available.refresh_from_db()
        self.assertEqual(available.status, Plot.Status.AVAILABLE)
        self.assertFalse(PlotStatusHistory.objects.filter(plot=available).exists())

    def test_cross_organization_operations_are_hidden_and_read_only_role_cannot_modify(self):
        foreign = self.other_plot()
        for operation in ("status", "block", "hold", "release"):
            payload = self.status_payload("blocked") if operation == "status" else {"reason": "x"}
            self.assertEqual(self.client.post(self.operation_url(foreign, operation), payload, format="json").status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory:plot-history", args=[self.organization.slug, foreign.id])).status_code, 404)
        bulk_url = reverse("inventory:plot-bulk-status", args=[self.organization.slug])
        self.assertEqual(self.client.post(bulk_url, {"plot_ids": [foreign.id], "status": "blocked", "reason": "x"}, format="json").status_code, 400)

        viewer = APIClient()
        viewer.force_authenticate(self.telecaller)
        own_plot = self.plot(number="A-viewer")
        self.assertEqual(viewer.post(self.status_url(own_plot), self.status_payload("blocked"), format="json").status_code, 403)
        self.assertEqual(viewer.post(bulk_url, {"plot_ids": [own_plot.id], "status": "blocked", "reason": "x"}, format="json").status_code, 403)
