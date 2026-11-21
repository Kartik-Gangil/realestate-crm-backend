from decimal import Decimal
from io import StringIO
from importlib import import_module

from django.core import management
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project
from leads.models import Lead
from system_settings.models import AuditLog

from .customer_services import (
    advance_customer_lifecycle,
    create_customer,
    customer_360_data,
    set_customer_status,
)
from .models import Block, Customer, CustomerNote, Payment, Plot, PlotBooking
from .customer_constraints import find_customer_collisions


class Phase10CustomerTests(TestCase):
    """FR-P10-01–06, EC-P10-01, NFR-P10-01, DM-P10-01/02, API-P10-01–04."""

    def setUp(self):
        self.organization = make_organization("phase10-customer")
        self.project = make_project(self.organization, "P10")
        self.block = Block.objects.create(
            organization=self.organization,
            project=self.project,
            name="Block A",
            code="A",
        )
        self.manager_membership = make_member(
            self.organization, role="manager", projects=[self.project]
        )
        self.manager = self.manager_membership.user
        self.telecaller_membership = make_member(
            self.organization, role="telecaller", projects=[self.project]
        )
        self.telecaller = self.telecaller_membership.user
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="Primary",
            phone="9000000101",
            email="primary@example.com",
            lifecycle_status="site_visit_completed",
            assigned_membership=self.telecaller_membership,
        )

    def make_customer(self, **overrides):
        values = {
            "organization": self.organization,
            "project": self.project,
            "full_name": "Primary Customer",
            "phone": "9000000101",
            "email": "primary@example.com",
            "address": "Address",
            "government_id_type": "PAN",
            "government_id": "ABCDE1234F",
            "lead": self.lead,
            "actor": self.manager,
        }
        values.update(overrides)
        return create_customer(**values)

    def make_booking(self, customer, status=PlotBooking.Status.PENDING):
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number=f"A-{Plot.objects.count() + 1}",
            size=Decimal("100"),
            total_price=Decimal("1000.00"),
        )
        return PlotBooking.objects.create(
            organization=self.organization,
            project=self.project,
            lead=customer.lead,
            customer=customer,
            plot=plot,
            status=status,
            final_price=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            net_amount=Decimal("1000.00"),
        )

    def test_manual_customer_starts_new_and_automatic_moves_never_go_backward(self):
        customer = self.make_customer()
        self.assertEqual(customer.status, Customer.Status.NEW)
        advance_customer_lifecycle(customer, Customer.Status.ACTIVE)
        advance_customer_lifecycle(customer, Customer.Status.ENGAGED)
        advance_customer_lifecycle(customer, Customer.Status.CONVERTED)
        advance_customer_lifecycle(customer, Customer.Status.ACTIVE)
        customer.refresh_from_db()
        self.assertEqual(customer.status, Customer.Status.CONVERTED)

    def test_manual_status_changes_require_reason_and_manager_or_admin(self):
        customer = self.make_customer()
        with self.assertRaises(ValidationError):
            set_customer_status(customer, Customer.Status.INACTIVE, "", self.manager)
        set_customer_status(customer, Customer.Status.INACTIVE, "Requested by owner", self.manager)
        with self.assertRaises(PermissionDenied):
            set_customer_status(customer, Customer.Status.BLACKLISTED, "Fraud", self.telecaller)
        set_customer_status(customer, Customer.Status.ACTIVE, "Verified and reactivated", self.manager)
        customer.refresh_from_db()
        self.assertEqual(customer.status, Customer.Status.ACTIVE)

    def test_360_totals_are_exact_decimal_and_count_several_payments(self):
        customer = self.make_customer()
        booking = self.make_booking(customer)
        for amount, payment_id in (("123.45", "P10-1"), ("222.22", "P10-2")):
            Payment.objects.create(
                organization=self.organization,
                booking=booking,
                payment_id=payment_id,
                amount=Decimal(amount),
                payment_method="cash",
                status=Payment.Status.SUCCESS,
                payment_date="2026-11-21",
            )
        data = customer_360_data(customer)
        self.assertEqual(data["totals"]["bookings_count"], 1)
        self.assertEqual(data["totals"]["total_paid"], Decimal("345.67"))
        self.assertEqual(data["totals"]["outstanding"], Decimal("654.33"))

    def test_customer_notes_are_immutable_and_appear_in_360_timeline(self):
        customer = self.make_customer()
        note = CustomerNote.objects.create(customer=customer, author=self.manager, note_text="Call summary")
        with self.assertRaises(ValidationError):
            note.save()
        with self.assertRaises(ValidationError):
            CustomerNote.objects.filter(pk=note.pk).delete()
        timeline = customer_360_data(customer)["timeline"]
        self.assertEqual(timeline[-1]["type"], "note")

    def test_government_id_is_encrypted_masked_and_absent_from_audit_payload(self):
        customer = self.make_customer()
        self.assertNotEqual(customer.government_id_encrypted, "ABCDE1234F")
        self.assertEqual(customer.government_id_last4, "234F")
        self.assertEqual(customer.government_id_hash, customer.identity_hash("ABCDE1234F"))
        audit = AuditLog.objects.filter(target_type="Customer", target_id=str(customer.pk)).order_by("-id").first()
        self.assertIsNotNone(audit)
        self.assertNotIn("ABCDE1234F", str(audit.payload_after))
        self.assertNotIn("1234F", str(audit.payload_after))

    def test_application_uniqueness_returns_existing_profile_link(self):
        existing = self.make_customer()
        with self.assertRaises(ValidationError) as context:
            self.make_customer(full_name="Another", phone="9000000102", email="primary@example.com")
        self.assertEqual(context.exception.code, "customer_duplicate")
        self.assertEqual(context.exception.message_dict["existing_customer_id"], [str(existing.pk)])

    def test_customer_delete_is_refused_at_model_and_queryset_levels(self):
        customer = self.make_customer()
        with self.assertRaises(ValidationError):
            customer.delete()
        with self.assertRaises(ValidationError):
            Customer.objects.filter(pk=customer.pk).delete()

    def test_resolver_correct_phone_and_merge_move_rows_without_deleting_customer(self):
        kept = self.make_customer()
        merged_lead = make_lead(self.organization, self.project, first_name="Merged", phone="9000000103")
        merged = self.make_customer(
            full_name="Merged Customer", phone="9000000103", email="merged@example.com", government_id="", lead=merged_lead,
        )
        booking = self.make_booking(merged)
        CustomerNote.objects.create(customer=merged, author=self.manager, note_text="Move me")
        management.call_command(
            "resolve_customer_duplicate", "merge", "--keep", kept.customer_code,
            "--merge", merged.customer_code, "--apply", stdout=StringIO(),
        )
        booking.refresh_from_db()
        merged.refresh_from_db()
        self.assertEqual(booking.customer_id, kept.pk)
        self.assertTrue(CustomerNote.objects.filter(customer=kept, note_text="Move me").exists())
        self.assertEqual(merged.status, Customer.Status.INACTIVE)
        self.assertEqual(merged.phone, "")
        self.assertEqual(merged.email, "")
        self.assertTrue(Customer.objects.filter(pk=merged.pk).exists())
        self.assertTrue(AuditLog.objects.filter(module="customers", action="merge").exists())

        output = StringIO()
        management.call_command(
            "resolve_customer_duplicate", "correct-phone", "--customer", kept.customer_code,
            "--phone", "9876543210", "--dry-run", stdout=output,
        )
        self.assertIn("mode=dry-run", output.getvalue())
        management.call_command(
            "resolve_customer_duplicate", "correct-phone", "--customer", kept.customer_code,
            "--phone", "9876543210", "--apply", stdout=StringIO(),
        )
        kept.refresh_from_db()
        self.assertEqual(kept.phone, "+919876543210")

    def test_collision_inventory_reports_counts_without_personal_data(self):
        self.make_customer()
        second_lead = make_lead(self.organization, self.project, first_name="Second", phone="9000000104")
        self.make_customer(full_name="Second", phone="9000000104", email="second@example.com", government_id="", lead=second_lead)
        collisions = find_customer_collisions(self.project)
        self.assertEqual(collisions, {"phone": 0, "email": 0, "government_id_hash": 0})

    def test_constraint_migration_stops_on_collision_counts(self):
        migration = import_module("inventory.migrations.0020_customer_identity_constraints")

        class FakeQuerySet:
            def filter(self, **kwargs):
                return self

            def exclude(self, **kwargs):
                return self

            def values(self, *args):
                return self

            def annotate(self, **kwargs):
                return self

            def count(self):
                return 1

        class FakeCustomer:
            objects = FakeQuerySet()

        class FakeApps:
            def get_model(self, app, model):
                return FakeCustomer

        with self.assertRaisesRegex(RuntimeError, "phone=1"):
            migration.stop_on_customer_collisions(FakeApps(), None)

    def test_customer_api_is_project_scoped_and_notes_are_postable(self):
        customer = self.make_customer()
        client = APIClient()
        client.force_authenticate(self.telecaller)
        headers = {"HTTP_X_PROJECT_ID": str(self.project.pk)}
        response = client.get(f"/api/v1/organizations/{self.organization.slug}/customers/", **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        detail = client.get(
            f"/api/v1/organizations/{self.organization.slug}/customers/{customer.pk}/360/", **headers
        )
        self.assertEqual(detail.status_code, 200)
        note = client.post(
            f"/api/v1/organizations/{self.organization.slug}/customers/{customer.pk}/notes/",
            {"note_text": "Telecaller note"}, format="json", **headers,
        )
        self.assertEqual(note.status_code, 201)

    def test_customer_scope_hides_unassigned_customer_from_telecaller(self):
        self.make_customer()
        other_lead = make_lead(self.organization, self.project, first_name="Other", phone="9000000105")
        create_customer(
            organization=self.organization, project=self.project, lead=other_lead,
            full_name="Other Customer", phone="9000000105", email="other@example.com", actor=self.manager,
        )
        client = APIClient()
        client.force_authenticate(self.telecaller)
        response = client.get(
            f"/api/v1/organizations/{self.organization.slug}/customers/",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

