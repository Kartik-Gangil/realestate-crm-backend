from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, Project
from organizations.services import ensure_default_roles
from system_settings.models import MasterData


class Phase2LeadSourceMasterDataTests(APITestCase):
    """FR-P2-01 / GNFR-09: lead sources come from active project master data."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lead-source-admin",
            email="lead-source-admin@example.test",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Lead Source Org", slug="lead-source-org")
        ensure_default_roles(self.organization)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Lead Source Project",
            code="SOURCE",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Other Source Project",
            code="OTHER-SOURCE",
        )
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)
        self.leads_url = f"/api/v1/organizations/{self.organization.slug}/leads/"
        self.sources_url = f"/api/v1/organizations/{self.organization.slug}/settings/masters/lead_source/"

    def lead_payload(self, source):
        return {
            "first_name": "Asha",
            "phone": "9000000001",
            "source": source,
        }

    def test_default_sources_are_seeded_as_system_items_and_accepted(self):
        response = self.client.post(self.leads_url, self.lead_payload("website"), format="json")

        self.assertEqual(response.status_code, 201)
        sources = MasterData.all_objects.filter(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
        )
        self.assertEqual(
            set(sources.values_list("code", flat=True)),
            {"fb", "ig", "website", "site_visit", "other", "walk_in"},
        )
        self.assertFalse(sources.filter(is_system=False).exists())

    def test_deactivated_source_is_rejected_immediately(self):
        self.client.post(self.leads_url, self.lead_payload("website"), format="json")
        website = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
            code="website",
        )
        deactivated = self.client.patch(
            f"{self.sources_url}{website.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(deactivated.status_code, 200)

        rejected = self.client.post(self.leads_url, self.lead_payload("website"), format="json")

        self.assertEqual(rejected.status_code, 400)
        self.assertIn("source", rejected.data)
        self.assertEqual(Lead.objects.count(), 1)

    def test_project_custom_source_is_accepted_without_model_choices(self):
        custom = self.client.post(
            self.sources_url,
            {"code": "partner_portal", "name": "Partner Portal"},
            format="json",
        )
        self.assertEqual(custom.status_code, 201)

        created = self.client.post(
            self.leads_url,
            self.lead_payload("partner_portal"),
            format="json",
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["source"], "partner_portal")
        self.assertEqual(Lead.objects.get().source, "partner_portal")
        self.assertFalse(Lead._meta.get_field("source").choices)

    def test_source_from_another_project_is_rejected(self):
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.other_project,
            master_type="lead_source",
            code="other_project_only",
            name="Other Project Only",
        )

        response = self.client.post(
            self.leads_url,
            self.lead_payload("other_project_only"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("source", response.data)

    def test_lead_update_rejects_source_deactivated_after_creation(self):
        created = self.client.post(self.leads_url, self.lead_payload("website"), format="json")
        website = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="lead_source",
            code="website",
        )
        website.is_active = False
        website.save(update_fields=["is_active"])

        response = self.client.patch(
            f"{self.leads_url}{created.data['id']}/",
            {"source": "website"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("source", response.data)
