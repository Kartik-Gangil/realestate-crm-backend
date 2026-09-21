from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from organizations.models import Organization

from .models import Block, Plot


class InventoryModelTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        self.block = Block.objects.create(organization=self.organization, name="A Block", code="A")

    def make_plot(self, **overrides):
        values = {
            "organization": self.organization,
            "block": self.block,
            "plot_number": "101",
            "size": Decimal("120.00"),
            "rate_per_sq_unit": Decimal("500.00"),
            "total_price": Decimal("60000.00"),
        }
        values.update(overrides)
        return Plot.objects.create(**values)

    def test_block_creation_and_relationship(self):
        self.assertEqual(self.block.organization, self.organization)

    def test_plot_creation_defaults_to_available(self):
        plot = self.make_plot()
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)
        self.assertEqual(plot.block.organization, plot.organization)

    def test_plot_number_is_unique_within_inventory_hierarchy(self):
        self.make_plot()
        with self.assertRaises(IntegrityError):
            self.make_plot()

    def test_organization_consistency_validation(self):
        plot = Plot(
            organization=self.other_organization, block=self.block,
            plot_number="102", size=Decimal("120.00"),
        )
        with self.assertRaises(ValidationError):
            plot.full_clean()

    def test_block_is_scoped_to_its_organization(self):
        block = Block.objects.create(
            organization=self.other_organization, name="Other Block", code="I"
        )
        self.assertEqual(block.organization, self.other_organization)

    def test_invalid_numeric_values_are_rejected(self):
        plot = Plot(
            organization=self.organization, block=self.block,
            plot_number="102", size=Decimal("0"), rate_per_sq_unit=Decimal("-1"),
            total_price=Decimal("-1"),
        )
        with self.assertRaises(ValidationError):
            plot.full_clean()
