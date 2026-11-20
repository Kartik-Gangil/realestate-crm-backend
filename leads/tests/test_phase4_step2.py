from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from inventory.models import Project
from leads.models import Lead
from system_settings.models import MasterData, MasterDataCategory


class Phase4Step2LeadFieldsTests(TestCase):
    """DM-P4-01 / GNFR-09 / Phase 4 Step 2 tests."""

    def setUp(self):
        self.organization = make_organization("phase4-step2")
        self.project = make_project(self.organization, "MAIN")

    def test_lead_has_phase4_fields(self):
        field_names = {field.name for field in Lead._meta.get_fields()}
        self.assertTrue({"lead_code", "status", "source_item", "score", "budget_range", "preferred_location", "external_source", "external_id"}.issubset(field_names))

    def test_new_projects_have_lead_master_data(self):
        expected_stages = {"new", "contacted", "qualified", "site_visit", "negotiation", "won", "lost"}
        expected_sources = {"fb", "ig", "website", "site_visit", "walk_in", "other", "google"}
        self.assertTrue(expected_stages.issubset(set(MasterData.objects.filter(project=self.project, category__code="lead_stage").values_list("code", flat=True))))
        self.assertTrue(expected_sources.issubset(set(MasterData.objects.filter(project=self.project, category__code="lead_source").values_list("code", flat=True))))

    def test_two_leads_get_sequential_codes_per_project(self):
        first = Lead.objects.create(organization=self.organization, project=self.project, first_name="First", phone="9876543210", source="website")
        second = Lead.objects.create(organization=self.organization, project=self.project, first_name="Second", phone="9876543211", source="website")
        self.assertEqual(first.lead_code, "MAIN-L-000001")
        self.assertEqual(second.lead_code, "MAIN-L-000002")

    def test_lead_code_is_unique_within_project(self):
        Lead.objects.create(organization=self.organization, project=self.project, first_name="First", phone="9876543210", source="website", lead_code="MAIN-L-000777")
        with self.assertRaises(IntegrityError):
            Lead.objects.create(organization=self.organization, project=self.project, first_name="Second", phone="9876543211", source="website", lead_code="MAIN-L-000777")

    def test_v1_api_exposes_phase4_field_names(self):
        membership = make_member(self.organization, role="manager", projects=[self.project])
        lead = Lead.objects.create(organization=self.organization, project=self.project, first_name="Api", phone="9876543210", source="website")
        client = APIClient()
        client.force_authenticate(membership.user)
        response = client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200)
        result = next(item for item in response.data["results"] if item["id"] == lead.id)
        self.assertIn("lead_code", result)
        self.assertIn("full_name", result)
        self.assertIn("owner_id", result)
        self.assertIn("status_id", result)
        self.assertIn("source_id", result)
