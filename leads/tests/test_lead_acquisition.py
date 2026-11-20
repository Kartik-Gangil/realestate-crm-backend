from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead


class ManualLeadAcquisitionApiTests(TestCase):
    def setUp(self):
        self.organization = make_organization("acme")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.user = self.membership.user
        self.existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="08871596881",
            source=Lead.Source.WEBSITE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_duplicate_check_is_available_on_the_organization_scoped_route(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/check-duplicate/",
            {"phone": "088 715 96881"},
            format="json",
            **project_request_kwargs(self.project),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([match["id"] for match in response.data["matches"]], [self.existing.id])
