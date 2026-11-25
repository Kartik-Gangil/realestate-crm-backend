from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead
from system_settings.models import MasterData, MasterDataCategory


class UATBug01DynamicLeadSourceTests(TestCase):
    """BUG-01 / FR-P2-01 / FR-P4-02 / API-P4-03 / GNFR-09."""

    def setUp(self):
        self.organization = make_organization("uat-bug-01")
        self.project = make_project(self.organization, "MAIN")
        self.other_project = make_project(self.organization, "OTHER")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        self.url = f"/api/v1/organizations/{self.organization.slug}/leads/manual/"
        self.request_kwargs = project_request_kwargs(self.project)
        self.source = MasterData.objects.create(
            organization=self.organization,
            project=self.project,
            category=MasterDataCategory.objects.get(code="lead_source"),
            code="uat_src",
            name="UAT Test Source",
        )

    def payload(self, **overrides):
        value = {
            "first_name": "UAT",
            "last_name": "Source",
            "phone": "9876543210",
            "email": "uat.source@example.com",
            "source": self.source.code,
            "status": "new",
        }
        value.update(overrides)
        return value

    def test_active_project_source_creates_lead(self):
        response = self.client.post(self.url, self.payload(), format="json", **self.request_kwargs)

        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual(lead.source_item_id, self.source.id)
        self.assertEqual(lead.source, self.source.code)

    def test_inactive_project_source_is_rejected(self):
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])

        response = self.client.post(self.url, self.payload(phone="9876543211"), format="json", **self.request_kwargs)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.json()["error"]["details"]["source"][0],
            "Use an active lead source from this project.",
        )

    def test_foreign_project_source_is_rejected(self):
        foreign_source = MasterData.objects.create(
            organization=self.organization,
            project=self.other_project,
            category=self.source.category,
            code="foreign_src",
            name="Foreign Project Source",
        )

        response = self.client.post(
            self.url,
            self.payload(phone="9876543212", source=foreign_source.code),
            format="json",
            **self.request_kwargs,
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.json()["error"]["details"]["source"][0],
            "Use an active lead source from this project.",
        )
