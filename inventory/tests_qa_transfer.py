from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from inventory.models import Block, Plot, PlotBooking, PlotSelection, Project
from leads.models import Lead
from organizations.models import Organization


class QaDataTransferCommandTests(TestCase):
    def setUp(self):
        call_command("seed_qa_flow_data", stdout=StringIO())
        self.source = Organization.objects.get(slug="qa-demo-org")
        self.target = Organization.objects.create(name="Target Organization", slug="shrijienclave")
        self.target_project = Project.objects.create(
            organization=self.target, name="Test Project", code="test"
        )

    def test_dry_run_reports_without_mutating_data(self):
        output = StringIO()

        call_command("transfer_qa_data", "--dry-run", stdout=output)

        self.assertIn("DRY RUN", output.getvalue())
        self.assertTrue(Organization.objects.filter(pk=self.source.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.target_project.pk).exists())
        self.assertEqual(Lead.objects.filter(email__endswith="@qa-demo.invalid").count(), 3)
        self.assertEqual(Plot.objects.filter(plot_number__startswith="QA-").count(), 6)

    def test_transfers_all_qa_records_and_deletes_source(self):
        lead = Lead.objects.filter(organization=self.source).first()
        plot = Plot.objects.filter(organization=self.source).first()
        booking = PlotBooking.objects.create(organization=self.source, lead=lead, plot=plot)
        selection = PlotSelection.objects.create(
            organization=self.source, plot=plot, lead=lead, selected_by=None
        )

        call_command("transfer_qa_data", stdout=StringIO())

        self.assertFalse(Organization.objects.filter(pk=self.source.pk).exists())
        self.assertEqual(Project.objects.filter(pk=self.target_project.pk).count(), 1)
        self.assertEqual(Lead.objects.filter(organization=self.target, email__endswith="@qa-demo.invalid").count(), 3)
        self.assertEqual(Plot.objects.filter(organization=self.target, project=self.target_project, plot_number__startswith="QA-").count(), 6)
        booking.refresh_from_db()
        selection.refresh_from_db()
        self.assertEqual(booking.organization_id, self.target.id)
        self.assertEqual(booking.plot.project_id, self.target_project.id)
        self.assertEqual(selection.organization_id, self.target.id)
        self.assertEqual(selection.plot.project_id, self.target_project.id)

    def test_conflict_rolls_back_without_deleting_source(self):
        Block.objects.create(
            organization=self.target,
            project=self.target_project,
            name="Conflicting QA Block",
            code="QA-A",
        )

        with self.assertRaises(CommandError):
            call_command("transfer_qa_data", stdout=StringIO())

        self.assertTrue(Organization.objects.filter(pk=self.source.pk).exists())
        self.assertEqual(Lead.objects.filter(organization=self.source).count(), 3)
        self.assertEqual(Plot.objects.filter(organization=self.source).count(), 6)
