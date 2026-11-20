from unittest.mock import patch

from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient


class Task9AuthenticationSurfaceTests(TestCase):
    """Task 9: FR-P1-01/05/07, API-P1-01/03/04/05, GNFR-14, G-0 item 2."""

    def setUp(self):
        self.client = APIClient()

    def test_every_auth_view_is_a_crm_endpoint_on_both_prefixes_gnfr_14(self):
        expected = {
            "login": ("public", ("POST",)),
            "verify-otp": ("public", ("POST",)),
            "logout": ("user", ("POST",)),
            "me": ("user", ("GET",)),
            "forgot-password": ("public", ("POST",)),
            "reset-password": ("public", ("POST",)),
            "change-password": ("user", ("POST",)),
        }
        for prefix in ("/api/auth/", "/api/v1/auth/"):
            for route, (scope, methods) in expected.items():
                callback = resolve(f"{prefix}{route}/").func
                self.assertEqual(callback.crm_endpoint_spec["scope"], scope)
                self.assertEqual(callback.crm_endpoint_spec["methods"], methods)

    def test_auth_views_are_removed_from_pipeline_pending_gnfr_14(self):
        pending_path = __import__("pathlib").Path(__file__).resolve().parents[2] / "scripts" / "pipeline-pending.txt"
        pending = pending_path.read_text(encoding="utf-8")
        for view_name in (
            "users.views.login",
            "users.views.verify_otp",
            "users.views.logout",
            "users.views.me",
            "users.views.forgot_password",
            "users.views.reset_password",
            "users.views.change_password",
        ):
            self.assertNotIn(view_name, pending)

    @patch("users.views.send_mail")
    def test_forgot_password_accepts_email_only_g0_item_2(self, send_mail):
        response = self.client.post(
            "/api/v1/auth/forgot-password/",
            {"phone": "+919876543210"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        send_mail.assert_not_called()
