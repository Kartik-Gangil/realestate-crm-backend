from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from leads.models import Lead
from organizations.models import Organization

from .models import Block, Plot, Project


class AssignMissingProjectsCommandTests(TestCase):
    """FR-P0-01, FR-P0-02, G-1 item 5, GNFR-06, GNFR-15."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Assign Org", slug="assign-org")
        self.project = Project.objects.create(
            organization=self.organization, name="Target", code="TARGET"
        )
        self.foreign_organization = Organization.objects.create(
            name="Foreign Org", slug="foreign-assign-org"
        )
        Project.objects.create(
            organization=self.foreign_organization, name="Foreign", code="TARGET"
        )
        self.block = Block.objects.create(
            organization=self.organization, project=self.project, name="Assigned", code="ASSIGNED"
        )
        Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="1",
            size=Decimal("100"),
        )
        Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="2",
            size=Decimal("100"),
        )
        Lead.objects.create(
            organization=self.organization,
            first_name="Already assigned by fixture",
            project=self.project,
            phone="9000000099",
        )

    def test_dry_run_reports_safety_details_and_does_not_change_rows_fr_p0_02_g1_item_5(self):
        output = StringIO()

        call_command(
            "assign_missing_projects",
            "--dry-run",
            org="assign-org",
            project="TARGET",
            stdout=output,
        )

        text = output.getvalue()
        self.assertIn("Block=0", text)
        self.assertIn("Plot=0", text)
        self.assertNotIn("projectless_plot_1", text)
        self.assertEqual(Block.objects.filter(project__isnull=True).count(), 0)
        self.assertEqual(Plot.objects.filter(project__isnull=True).count(), 0)

    def test_apply_assigns_only_the_selected_organization_rows_fr_p0_02_gnfr_06(self):
        call_command(
            "assign_missing_projects",
            "--apply",
            org="assign-org",
            project="TARGET",
            stdout=StringIO(),
        )

        self.assertEqual(Block.objects.filter(organization=self.organization, project__isnull=True).count(), 0)
        self.assertEqual(Plot.objects.filter(organization=self.organization, project__isnull=True).count(), 0)
        self.assertEqual(Block.objects.filter(organization=self.foreign_organization, project__isnull=True).count(), 0)

    def test_foreign_project_code_is_refused_gnfr_06(self):
        with self.assertRaises(CommandError):
            call_command(
                "assign_missing_projects",
                "--dry-run",
                org="assign-org",
                project="FOREIGN",
                stdout=StringIO(),
            )

    @patch("inventory.management.commands.assign_missing_projects.collect_assignment_report")
    def test_dry_run_reports_all_safety_counts_against_fixture_fr_p0_02_g1_item_5(self, collect_report):
        collect_report.return_value = {
            "counts": {"Block": 4, "Plot": 6, "Lead": 0, "Sitevisit": 0, "Expense": 0},
            "plot_groups": {"ba1": 3, "tst": 1, "QA-A": 2},
            "bookings": 0,
            "selections": 0,
            "hold_records": 4,
            "unreleased_hold_records": 4,
            "linked_lead_projects": {"test": 2},
        }
        output = StringIO()

        call_command(
            "assign_missing_projects", "--dry-run", org="assign-org", project="TARGET", stdout=output
        )

        text = output.getvalue()
        self.assertIn("counts Block=4 Plot=6 Lead=0 Sitevisit=0 Expense=0", text)
        self.assertIn("plot_group block_code=ba1 rows=3", text)
        self.assertIn("plot_group block_code=tst rows=1", text)
        self.assertIn("plot_group block_code=QA-A rows=2", text)
        self.assertIn("relations bookings=0 selections=0 hold_records=4 unreleased_hold_records=4", text)
        self.assertIn("linked_lead_project=test count=2", text)
