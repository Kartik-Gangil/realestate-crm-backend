from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership
from system_settings.models import MasterData, MasterDataCategory, SystemParameter

from .models import Block, Plot, PlotBooking, PlotHold, Project
from .services import bulk_change_plot_status, create_idempotent_booking
from .receipt_pdf import booking_receipt_pdf


class Phase8FinalSprintTests(TestCase):
    """Task 7 / FR-P8-* / NFR-P8-* red tests for the final-sprint contract."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="phase8@example.com", email="phase8@example.com", password="password123"
        )
        self.organization = Organization.objects.create(name="Phase 8 Org", slug="phase8-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization, name="Phase 8 Project", code="P8"
        )
        self.block = Block.objects.create(
            organization=self.organization, project=self.project, name="Block A", code="A"
        )

    def make_plot(self, number="A-1", **overrides):
        values = {
            "organization": self.organization,
            "project": self.project,
            "block": self.block,
            "plot_number": number,
            "size": Decimal("100.00"),
            "total_price": Decimal("100000.00"),
        }
        values.update(overrides)
        return Plot.objects.create(**values)

    def test_fr_p8_03_registers_project_scoped_hold_duration(self):
        definition = __import__("system_settings.parameters", fromlist=["PARAMETER_REGISTRY"]).PARAMETER_REGISTRY[
            "plot_hold_hours"
        ]
        self.assertEqual(definition.scope, "project")
        self.assertEqual(definition.default, 24)
        self.assertEqual(definition.min_value, 1)
        self.assertEqual(definition.max_value, 168)

    def test_fr_p8_03_hold_has_expiry_and_locks_rechecks_the_plot(self):
        plot = self.make_plot()
        held = __import__("inventory.services", fromlist=["hold_plot"]).hold_plot(
            plot=plot, reason="Site visit requested", user=self.user
        )
        hold = PlotHold.objects.get(plot=held, released_at__isnull=True)
        self.assertIsNotNone(hold.expires_at)
        self.assertGreater(hold.expires_at, timezone.now())
        self.assertEqual(held.status, Plot.Status.HOLD)

    def test_nfr_p8_02_worker_reverts_expired_hold_but_leaves_unexpired_hold(self):
        expired = self.make_plot("A-1", status=Plot.Status.HOLD)
        current = self.make_plot("A-2", status=Plot.Status.HOLD)
        PlotHold.objects.create(
            plot=expired,
            action_type=PlotHold.ActionType.HOLD,
            reason="expired",
            expires_at=timezone.now() - timedelta(minutes=1),
            created_by=self.user,
        )
        PlotHold.objects.create(
            plot=current,
            action_type=PlotHold.ActionType.HOLD,
            reason="current",
            expires_at=timezone.now() + timedelta(hours=1),
            created_by=self.user,
        )
        from core.tasks_backend import process_due_reminders

        process_due_reminders()
        expired.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(expired.status, Plot.Status.AVAILABLE)
        self.assertEqual(current.status, Plot.Status.HOLD)

    def test_fr_p8_06_rejects_more_than_500_plots(self):
        plots = [self.make_plot(f"A-{index}") for index in range(1, 502)]
        with self.assertRaises(ValidationError):
            bulk_change_plot_status(plots=plots, new_status=Plot.Status.BLOCKED, reason="bulk", user=self.user)

    def test_fr_p8_06_bulk_status_rolls_back_when_one_plot_fails(self):
        first = self.make_plot("A-1")
        second = self.make_plot("A-2")
        from unittest.mock import patch
        import inventory.services as services

        original = services._change_locked_plot_status
        calls = {"count": 0}

        def fail_second(plot, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise ValidationError({"plot": "forced failure"})
            return original(plot, *args, **kwargs)

        with patch.object(services, "_change_locked_plot_status", side_effect=fail_second):
            with self.assertRaises(ValidationError):
                bulk_change_plot_status(plots=[first, second], new_status=Plot.Status.BLOCKED, reason="bulk", user=self.user)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Plot.Status.AVAILABLE)
        self.assertEqual(second.status, Plot.Status.AVAILABLE)


class Phase9FinalSprintTests(TestCase):
    """Task 8 / FR-P9-* / NFR-P9-* red tests for the final-sprint contract."""

    def test_fr_p9_04_has_the_six_booking_statuses(self):
        self.assertEqual(
            {choice[0] for choice in PlotBooking.Status.choices},
            {"created", "payment_pending", "partially_paid", "confirmed", "cancelled", "expired"},
        )

    def test_dm_p10_01_minimal_customer_table_exists(self):
        from .models import Customer

        field_names = {field.name for field in Customer._meta.fields}
        self.assertTrue({"customer_code", "organization", "project", "lead", "full_name", "phone", "email", "address", "status", "created_at"}.issubset(field_names))

    def test_fr_p9_09_booking_initiation_requires_named_booking_permission(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from . import views

        access = SimpleNamespace(
            is_platform=False,
            membership=SimpleNamespace(user=self.user),
            organization=self.organization,
            project=self.project,
        )
        with patch.object(views, "has_permission", side_effect=lambda user, organization, code, **kwargs: code == "plots.view"):
            with self.assertRaises(PermissionDenied):
                views._require_booking_creation(access)

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="phase9@example.com", email="phase9@example.com", password="password123"
        )
        self.organization = Organization.objects.create(name="Phase 9 Org", slug="phase9-org")
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role=OrganizationMembership.Role.ADMIN
        )
        self.project = Project.objects.create(organization=self.organization, name="Phase 9 Project", code="P9")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="Block A", code="A")
        self.plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-1",
            size=Decimal("100"),
            total_price=Decimal("100000"),
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Eligible",
            last_name="Lead",
            phone="9000000001",
            lifecycle_status="site_visit_completed",
        )
        MasterData.objects.get_or_create(
            organization=self.organization,
            project=self.project,
            category=MasterDataCategory.objects.get(code="payment_mode"),
            code="upi",
            defaults={"name": "UPI", "is_active": True},
        )

    def test_fr_p9_03_creates_customer_books_plot_and_replays_idempotently(self):
        body = {
            "lead_id": self.lead.pk,
            "plot_id": self.plot.pk,
            "initial_payment": "1000.00",
            "payment_mode": "upi",
            "transaction_reference": "P9-UPI-1",
        }
        booking = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            plot=self.plot,
            user=self.user,
            idempotency_key="phase9-key",
            body=body,
            initial_payment="1000.00",
            payment_mode="upi",
            transaction_reference="P9-UPI-1",
        )
        replay = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            plot=self.plot,
            user=self.user,
            idempotency_key="phase9-key",
            body=body,
            initial_payment="1000.00",
            payment_mode="upi",
            transaction_reference="P9-UPI-1",
        )
        self.assertEqual(replay.pk, booking.pk)
        self.assertEqual(self.plot.__class__.objects.get(pk=self.plot.pk).status, Plot.Status.BOOKED)
        self.assertEqual(booking.customer.project_id, self.project.pk)
        self.assertEqual(booking.status, PlotBooking.Status.PARTIALLY_PAID)

    def test_fr_p9_09_rejects_a_lead_before_site_visit_completed(self):
        self.lead.lifecycle_status = "interested"
        self.lead.save(update_fields=["lifecycle_status"])
        with self.assertRaises(ValidationError):
            create_idempotent_booking(
                organization=self.organization,
                project=self.project,
                lead=self.lead,
                plot=self.plot,
                user=self.user,
                idempotency_key="ineligible",
            )

    def test_fr_p9_08_booking_receipt_is_a_pdf_with_project_sequence(self):
        booking = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            plot=self.plot,
            user=self.user,
            idempotency_key="receipt",
        )
        pdf = booking_receipt_pdf(booking)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"P9-BR-000001", pdf)

    def test_nfr_p9_01_forced_plot_step_rolls_back_booking_customer_and_payment(self):
        from unittest.mock import patch

        with patch("inventory.services.change_plot_status", side_effect=ValidationError({"plot": "forced step failure"})):
            with self.assertRaises(ValidationError):
                create_idempotent_booking(
                    organization=self.organization,
                    project=self.project,
                    lead=self.lead,
                    plot=self.plot,
                    user=self.user,
                    idempotency_key="rollback",
                    initial_payment="1000",
                )
        self.assertFalse(PlotBooking.objects.exists())
        from .models import Customer, Payment
        self.assertFalse(Customer.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.AVAILABLE)

    def test_nfr_p9_03_same_key_different_body_is_a_conflict(self):
        body = {"lead_id": self.lead.pk, "plot_id": self.plot.pk, "initial_payment": "0"}
        create_idempotent_booking(
            organization=self.organization, project=self.project, lead=self.lead, plot=self.plot,
            user=self.user, idempotency_key="same-key", body=body,
        )
        with self.assertRaises(ValidationError) as raised:
            create_idempotent_booking(
                organization=self.organization, project=self.project, lead=self.lead, plot=self.plot,
                user=self.user, idempotency_key="same-key", body={**body, "initial_payment": "1"}, initial_payment="1",
            )
        self.assertEqual(getattr(raised.exception, "code", None), "idempotency_conflict")

    def test_fr_p9_06_and_ec_p9_01_worker_expires_booking_and_releases_plot(self):
        from core.tasks_backend import process_due_bookings
        from django.utils import timezone

        booking = create_idempotent_booking(
            organization=self.organization, project=self.project, lead=self.lead, plot=self.plot,
            user=self.user, idempotency_key="expiry",
        )
        PlotBooking.objects.filter(pk=booking.pk).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
        process_due_bookings()
        booking.refresh_from_db()
        self.plot.refresh_from_db()
        self.assertEqual(booking.status, PlotBooking.Status.EXPIRED)
        self.assertEqual(self.plot.status, Plot.Status.AVAILABLE)
