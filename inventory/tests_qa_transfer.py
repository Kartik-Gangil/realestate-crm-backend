from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from inventory.models import Block, Plot, PlotBooking, PlotSelection, Project
from leads.models import Lead, Sitevisit
from organizations.models import Organization
from system_settings.models import AuditLog, MasterData


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

    def test_transferred_leads_use_target_project_master_data(self):
        source_lead = Lead.objects.filter(organization=self.source).first()
        source_status_id = source_lead.status_id
        source_source_id = source_lead.source_item_id
        visit = Sitevisit.objects.create(
            organization=self.source,
            project=source_lead.project,
            lead=source_lead,
        )

        call_command("transfer_qa_data", stdout=StringIO())

        moved_lead = Lead.objects.get(pk=source_lead.pk)
        self.assertNotEqual(moved_lead.status_id, source_status_id)
        self.assertNotEqual(moved_lead.source_item_id, source_source_id)
        self.assertEqual(moved_lead.status.project_id, self.target_project.id)
        self.assertEqual(moved_lead.source_item.project_id, self.target_project.id)
        self.assertEqual(moved_lead.status.organization_id, self.target.id)
        self.assertEqual(moved_lead.source_item.organization_id, self.target.id)
        visit.refresh_from_db()
        self.assertEqual(visit.organization_id, self.target.id)
        self.assertEqual(visit.project_id, self.target_project.id)
        self.assertFalse(
            Lead.objects.filter(organization=self.target)
            .exclude(status__project=self.target_project, source_item__project=self.target_project)
            .exists()
        )
        self.assertFalse(
            MasterData.objects.filter(lead_status_items__organization=self.target)
            .exclude(project=self.target_project)
            .exists()
        )

    def test_project_deletion_audit_is_written_without_rewriting_prior_audits_gnfr_07_gnfr_15(self):
        source_project_id = self.source.inventory_projects.get(code="QA-DEMO").pk
        before = list(
            AuditLog.objects.filter(project_id=source_project_id)
            .values(
                "pk", "user_id", "module", "action", "method", "route",
                "ip_address", "details", "payload_before", "payload_after", "target_type", "target_id",
            )
        )
        self.assertTrue(before)

        call_command("transfer_qa_data", stdout=StringIO())

        deletion_rows = AuditLog.objects.filter(
            action="delete",
            target_type="Project",
            target_id=str(source_project_id),
        )
        self.assertEqual(deletion_rows.count(), 1)
        self.assertEqual(deletion_rows.get().details["deleted_project_id"], source_project_id)
        after = list(
            AuditLog.objects.filter(pk__in=[row["pk"] for row in before])
            .values(
                "pk", "user_id", "module", "action", "method", "route",
                "ip_address", "details", "payload_before", "payload_after", "target_type", "target_id",
            )
        )
        self.assertEqual(after, before)

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
