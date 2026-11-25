"""FR-P2-02 [UAT-D13] Support Email acceptance tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from .models import OrganizationSettings


class UatD13SupportEmailTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="UAT-D13 org", slug="uat-d13-org")
        self.admin = get_user_model().objects.create_user(
            username="admin@uat-d13.test",
            email="admin@uat-d13.test",
            password="Admin123!",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role="admin",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f"/api/v1/organizations/{self.organization.slug}/settings/general/"

    def test_support_email_is_optional_trimmed_and_lowercased(self):
        response = self.client.patch(
            self.url,
            {"support_email": "  SUPPORT@Example.COM  "},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["support_email"], "support@example.com")
        self.assertEqual(
            OrganizationSettings.objects.get(organization=self.organization).support_email,
            "support@example.com",
        )

        blank_response = self.client.patch(self.url, {"support_email": "   "}, format="json")
        self.assertEqual(blank_response.status_code, 200, blank_response.data)
        self.assertEqual(blank_response.data["support_email"], "")

    def test_invalid_or_oversized_support_email_returns_exact_field_error(self):
        invalid_response = self.client.patch(
            self.url,
            {"support_email": "not-an-email"},
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 400, invalid_response.data)
        self.assertEqual(invalid_response.data["support_email"][0], "Enter a valid support email address.")

        oversized_response = self.client.patch(
            self.url,
            {"support_email": "a" * 245 + "@example.com"},
            format="json",
        )
        self.assertEqual(oversized_response.status_code, 400, oversized_response.data)
        self.assertEqual(oversized_response.data["support_email"][0], "Enter a valid support email address.")
