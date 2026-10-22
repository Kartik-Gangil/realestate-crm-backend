from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership


class ManualLeadAcquisitionApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="manager", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.organization, name="Main", code="MAIN")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="08871596881",
            source=Lead.Source.WEBSITE,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=str(self.project.id))

    def test_duplicate_check_is_available_on_the_organization_scoped_route(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/check-duplicate/",
            {"phone": "088 715 96881"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([match["id"] for match in response.data["matches"]], [self.existing.id])
