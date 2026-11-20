from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from organizations.services import ensure_default_roles

from .models import DeveloperAccount


class Phase3FixRound4AuthProfileTests(TestCase):
    """FR-P3-08/UI-P3-04: auth responses expose the real developer marker."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Round Four Org", slug="round-four-org")
        roles = ensure_default_roles(self.organization)
        self.developer = get_user_model().objects.create_user(
            username="developer-round-four@example.test",
            email="developer-round-four@example.test",
            password="Developer-password-123!",
        )
        DeveloperAccount.objects.create(user=self.developer)
        self.admin = get_user_model().objects.create_user(
            username="admin-round-four@example.test",
            email="admin-round-four@example.test",
            password="Admin-password-123!",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role="admin",
            organization_role=roles["admin"],
        )
        self.super_admin = get_user_model().objects.create_superuser(
            "super-round-four@example.test",
            "super-round-four@example.test",
            "Super-password-123!",
        )
        self.platform_admin = get_user_model().objects.create_user(
            username="platform-round-four@example.test",
            email="platform-round-four@example.test",
            password="Platform-password-123!",
        )
        self.platform_admin.groups.add(Group.objects.create(name="Platform Admin"))
        self.client = APIClient()

    def _profile(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()["data"]

    def test_auth_me_returns_developer_marker_for_developer_and_false_for_admin_and_super_admin(self):
        self.assertTrue(self._profile(self.developer)["is_developer"])
        self.assertFalse(self._profile(self.admin)["is_developer"])
        self.assertFalse(self._profile(self.super_admin)["is_developer"])

    def test_login_response_contains_developer_marker(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.developer.email, "password": "Developer-password-123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.json()["data"]["user"]["is_developer"])

    def test_platform_admin_profile_is_labelable_without_membership(self):
        profile = self._profile(self.platform_admin)
        self.assertTrue(profile["is_platform_admin"])
