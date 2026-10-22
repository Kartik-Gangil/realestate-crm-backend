from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import Project
from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership


class SiteVisitProjectContextTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="sitevisit-admin@example.com",
            email="sitevisit-admin@example.com",
            password="Valid123!",
            is_superuser=True,
        )
        self.organization = Organization.objects.create(name="Visits Org", slug="visits-org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role="admin")
        self.project_a = Project.objects.create(organization=self.organization, name="Project A", code="A")
        self.project_b = Project.objects.create(organization=self.organization, name="Project B", code="B")
        self.lead_a = Lead.objects.create(
            organization=self.organization, project=self.project_a,
            first_name="Lead", last_name="A", phone="9000000001",
        )
        self.lead_b = Lead.objects.create(
            organization=self.organization, project=self.project_b,
            first_name="Lead", last_name="B", phone="9000000002",
        )
        self.visit_a = Sitevisit.objects.create(
            organization=self.organization, project=self.project_a, lead=self.lead_a,
            visit_date=timezone.localdate() + timedelta(days=1), visit_time="10:00", site="A",
        )
        self.visit_b = Sitevisit.objects.create(
            organization=self.organization, project=self.project_b, lead=self.lead_b,
            visit_date=timezone.localdate() + timedelta(days=1), visit_time="11:00", site="B",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_site_visit_list_is_scoped_by_project_header(self):
        url = "/api/organizations/visits-org/sitevisits/"
        self.assertEqual(self.client.get(url).status_code, 400)
        response = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.visit_a.id])
