from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from leads.models import Lead
from organizations.models import Organization
from system_settings.models import MasterData, MasterDataCategory

from .models import Block, Plot, PlotBooking, Project
from .phase5_services import _payment_mode_is_valid, calculate_registry_charges


class ProjectConfigurationReaderTests(TestCase):
    """G-1 item 4 and GNFR-06: configuration reads stay project-local."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Config Org", slug="config-org")
        self.project = Project.objects.create(
            organization=self.organization, name="Project", code="PROJECT"
        )
        block = Block.objects.create(
            organization=self.organization, project=self.project, name="Block", code="BLOCK"
        )
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=block,
            plot_number="1",
            size=Decimal("100"),
            total_price=Decimal("1000"),
        )
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Project lead",
            phone="9000000088",
        )
        self.booking = PlotBooking.objects.create(
            organization=self.organization, lead=lead, plot=plot
        )

    def test_payment_mode_reader_uses_project_rows_only_g1_item_4(self):
        category = MasterDataCategory.objects.get(code="payment_mode")
        MasterData.objects.create(
            organization=self.organization,
            category=category,
            code="default-mode",
            name="Default mode",
        )
        MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="project-mode",
            name="Project mode",
        )

        self.assertEqual(
            _payment_mode_is_valid(self.organization, "project-mode", project=self.project),
            "project-mode",
        )
        with self.assertRaises(ValidationError):
            _payment_mode_is_valid(self.organization, "default-mode", project=self.project)

    def test_registry_charge_reader_uses_project_rows_only_g1_item_4(self):
        category = MasterDataCategory.objects.get(code="registry_charge_type")
        MasterData.objects.create(
            organization=self.organization,
            category=category,
            code="default-charge",
            name="Default charge",
            description="fixed:10",
        )
        MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=category,
            code="project-charge",
            name="Project charge",
            description="fixed:20",
        )

        rows = calculate_registry_charges(
            organization=self.organization,
            booking=self.booking,
            consideration_amount=Decimal("1000"),
        )

        self.assertEqual([row[0] for row in rows], ["project-charge"])
