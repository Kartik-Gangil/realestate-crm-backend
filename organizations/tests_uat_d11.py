"""FR-P1-05 / FR-P3-01 [UAT-D11] password-reset link acceptance tests."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership
from .services import ensure_default_roles


class UatD11PasswordResetTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="UAT-D11 org", slug="uat-d11-org")
        self.roles = ensure_default_roles(self.organization)
        self.admin = self._member("admin@example.test", "admin", "Admin123!")
        self.target = self._member("target@example.test", "telecaller", "OldPassword123!")
        self.client = APIClient()
        self.client.force_authenticate(self.admin.user)

    def _member(self, email, role, password):
        user = get_user_model().objects.create_user(username=email, email=email, password=password)
        return OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            role=role,
            organization_role=self.roles[role],
        )

    def _url(self):
        return f"/api/v1/organizations/{self.organization.slug}/users/{self.target.pk}/reset-password/"

    @patch("users.views.send_mail", return_value=1)
    def test_admin_reset_emails_token_link_without_exposing_a_password(self, send_mail):
        response = self.client.post(self._url(), {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["detail"], "Password reset link sent.")
        self.assertNotIn("password", response.data)
        send_mail.assert_called_once()
        self.assertIn("uid=", send_mail.call_args.args[1])
        self.assertIn("token=", send_mail.call_args.args[1])
        self.assertTrue(self.target.user.check_password("OldPassword123!"))

    @patch("users.views.send_mail", side_effect=OSError("SMTP unavailable"))
    def test_admin_reset_returns_clear_email_configuration_error(self, send_mail):
        response = self.client.post(self._url(), {}, format="json")

        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data["code"], "email_not_configured")
        self.assertEqual(
            response.data["detail"],
            "Password reset email could not be sent. Configure email delivery and try again.",
        )
        self.assertTrue(self.target.user.check_password("OldPassword123!"))
