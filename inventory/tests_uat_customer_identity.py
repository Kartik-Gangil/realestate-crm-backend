from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from django.test import TestCase

from core.tests.factories import make_lead, make_member, make_organization, make_project
from documents.views import _customer as document_customer
from inventory.customer_services import create_customer
from inventory.models import Block, Customer, Plot, Registry
from organizations.services import get_organization_access
from inventory.services import create_idempotent_booking
from inventory.views import managed_registry_to_dict


class UatCustomerIdentityTests(TestCase):
    """UAT LC-05/RT-01 and LC-15 regression coverage."""

    def setUp(self):
        self.organization = make_organization("uat-customer-identity")
        self.project = make_project(self.organization, "UCI")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.user = self.membership.user
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="Booking Lead",
            lifecycle_status="site_visit_completed",
        )
        self.customer = create_customer(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            full_name="Existing Customer",
            phone="9000000199",
            email="existing-customer@example.com",
        )
        self.block = Block.objects.create(
            organization=self.organization,
            project=self.project,
            name="Block A",
            code="A",
        )
        self.plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-1",
            size=Decimal("100"),
            total_price=Decimal("100000.00"),
        )

    def test_document_customer_lookup_resolves_inventory_customer_lc05_rt01(self):
        access = get_organization_access(self.user, self.organization.slug)

        resolved = document_customer(access, self.customer.pk, self.project)

        self.assertIsInstance(resolved, Customer)
        self.assertEqual(resolved.pk, self.customer.pk)

    def test_booking_uses_selected_existing_customer_lc15(self):
        before_count = Customer.objects.filter(project=self.project).count()

        booking = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            customer=self.customer,
            plot=self.plot,
            user=self.user,
            idempotency_key="uat-customer-identity-booking",
            body={
                "lead_id": self.lead.pk,
                "customer_id": self.customer.pk,
                "plot_id": self.plot.pk,
            },
        )

        self.assertEqual(booking.customer_id, self.customer.pk)
        self.assertEqual(Customer.objects.filter(project=self.project).count(), before_count)

    def test_plot_price_is_calculated_from_size_and_rate_lc08(self):
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-2",
            size=Decimal("1000"),
            rate_per_sq_unit=Decimal("2000"),
        )

        self.assertEqual(plot.total_price, Decimal("2000000.00"))

    def test_booking_copies_calculated_plot_price_lc08(self):
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-3",
            size=Decimal("1000"),
            rate_per_sq_unit=Decimal("2000"),
        )

        booking = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            customer=self.customer,
            plot=plot,
            user=self.user,
            idempotency_key="uat-price-booking",
            body={"lead_id": self.lead.pk, "customer_id": self.customer.pk, "plot_id": plot.pk},
        )

        self.assertEqual(booking.final_price, Decimal("2000000.00"))
        self.assertEqual(booking.total_amount, Decimal("2000000.00"))
        self.assertEqual(booking.net_amount, Decimal("2000000.00"))

    def test_registry_number_does_not_replace_stable_registry_id_rt02_lc14(self):
        booking = create_idempotent_booking(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            customer=self.customer,
            plot=self.plot,
            user=self.user,
            idempotency_key="uat-registry-identity",
            body={"lead_id": self.lead.pk, "customer_id": self.customer.pk, "plot_id": self.plot.pk},
        )
        registry = Registry.objects.create(
            organization=self.organization,
            booking=booking,
            registry_number="REG-2",
            created_by=self.user,
        )

        before = managed_registry_to_dict(registry)
        registry.registry_number = "REG-RT-PATCH"
        registry.save(update_fields=["registry_number"])
        after = managed_registry_to_dict(registry)

        self.assertEqual(before["registry_id"], f"REG-{registry.pk}")
        self.assertEqual(after["registry_id"], before["registry_id"])
        self.assertEqual(after["registry_number"], "REG-RT-PATCH")

    def test_booking_customer_backfill_uses_historical_lead_fields_lc05_rt01(self):
        migration = import_module("inventory.migrations.0021_backfill_booking_customers")
        historical_lead = SimpleNamespace(first_name="Asha", last_name="Sharma")

        self.assertEqual(migration._lead_name(historical_lead), "Asha Sharma")
