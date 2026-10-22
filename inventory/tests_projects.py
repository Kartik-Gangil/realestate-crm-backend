from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership

from .models import Project


class ProjectApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="admin@acme.test", email="admin@acme.test", password="password123"
        )
        self.manager = user_model.objects.create_user(
            username="manager@acme.test", email="manager@acme.test", password="password123"
        )
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN
        )
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER
        )
        self.project = Project.objects.create(
            organization=self.organization, name="Green Acres", code="GA", description="Main site"
        )
        Project.objects.create(organization=self.other_organization, name="Foreign", code="F")
        self.client = APIClient()

    def url(self):
        return f"/api/organizations/{self.organization.slug}/inventory/projects/"

    def test_admin_lists_only_projects_in_their_organization(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.project.id)

    def test_admin_can_create_a_project(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            self.url(), {"name": "Lake View", "code": "LV", "description": "Phase 2"}, format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Project.objects.filter(organization=self.organization, code="LV").exists())

    def test_non_admin_cannot_create_a_project(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(self.url(), {"name": "Nope", "code": "NO"}, format="json")

        self.assertEqual(response.status_code, 403)
