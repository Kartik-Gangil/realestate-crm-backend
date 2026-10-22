from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from inventory.models import Block, Plot, Project
from leads.models import Lead
from organizations.models import Organization


class QaFlowSeedCommandTests(TestCase):
    def test_seed_is_idempotent_and_creates_related_flow_data(self):
        call_command("seed_qa_flow_data", stdout=StringIO())
        first_counts = {
            "organizations": Organization.objects.filter(slug="qa-demo-org").count(),
            "projects": Project.objects.filter(code="QA-DEMO").count(),
            "blocks": Block.objects.filter(code="QA-A").count(),
            "leads": Lead.objects.filter(email__endswith="@qa-demo.invalid").count(),
            "plots": Plot.objects.filter(plot_number__startswith="QA-").count(),
        }

        call_command("seed_qa_flow_data", stdout=StringIO())
        second_counts = {
            "organizations": Organization.objects.filter(slug="qa-demo-org").count(),
            "projects": Project.objects.filter(code="QA-DEMO").count(),
            "blocks": Block.objects.filter(code="QA-A").count(),
            "leads": Lead.objects.filter(email__endswith="@qa-demo.invalid").count(),
            "plots": Plot.objects.filter(plot_number__startswith="QA-").count(),
        }

        self.assertEqual(first_counts, second_counts)
        self.assertEqual(first_counts["leads"], 3)
        self.assertEqual(first_counts["plots"], 6)

    def test_seed_preserves_existing_unrelated_records(self):
        organization = Organization.objects.create(name="Existing QA Organization", slug="existing-qa-org")
        project = Project.objects.create(organization=organization, name="Existing Project", code="EXISTING")
        block = Block.objects.create(organization=organization, project=project, name="Existing Block", code="EXISTING-A")
        lead = Lead.objects.create(
            organization=organization,
            first_name="Existing",
            last_name="Lead",
            email="existing@example.com",
            phone="9999999999",
        )
        plot = Plot.objects.create(
            organization=organization,
            project=project,
            block=block,
            plot_number="EXISTING-1",
            size="1000.00",
            rate_per_sq_unit="100.00",
            total_price="100000.00",
        )

        call_command("seed_qa_flow_data", stdout=StringIO())

        self.assertTrue(Organization.objects.filter(pk=organization.pk).exists())
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())
        self.assertTrue(Block.objects.filter(pk=block.pk).exists())
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())
        self.assertTrue(Plot.objects.filter(pk=plot.pk).exists())

    def test_seeded_records_have_valid_flow_relationships_and_statuses(self):
        call_command("seed_qa_flow_data", stdout=StringIO())

        organization = Organization.objects.get(slug="qa-demo-org")
        project = Project.objects.get(organization=organization, code="QA-DEMO")
        leads = Lead.objects.filter(organization=organization, email__endswith="@qa-demo.invalid")
        plots = Plot.objects.filter(organization=organization, project=project, plot_number__startswith="QA-")

        self.assertEqual(leads.count(), 3)
        self.assertTrue(all(lead.phone for lead in leads))
        self.assertEqual(plots.count(), 6)
        self.assertTrue(all(plot.block.project_id == project.id for plot in plots))
        self.assertSetEqual(
            set(plots.values_list("status", flat=True)),
            {Plot.Status.AVAILABLE, Plot.Status.HOLD, Plot.Status.BOOKED},
        )
