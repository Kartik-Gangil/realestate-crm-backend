from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from organizations.services import ensure_default_roles

from .otp import OtpInvalid


class Phase1AuthenticationSecurityTests(TestCase):
    """FR-P1-02 through FR-P1-07 and DM-P1-01/DM-P1-02."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="secure@example.com",
            email="secure@example.com",
            password="Valid123!",
        )
        organization = Organization.objects.create(name="Security Org", slug="security-org")
        role = ensure_default_roles(organization)["manager"]
        OrganizationMembership.objects.create(
            organization=organization, user=self.user, role="manager", organization_role=role
        )
        self.client = APIClient()

    def test_password_policy_requires_letter_number_and_symbol_on_change_password(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {"old_password": "Valid123!", "new_password": "Password1"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("new_password", response.data)

    def test_fifth_failed_password_attempt_locks_account_for_fifteen_minutes(self):
        for attempt in range(1, 5):
            response = self.client.post(
                "/api/v1/auth/login/",
                {"email": self.user.email, "password": "Wrong123!"},
                format="json",
            )
            self.assertEqual(response.status_code, 401, (attempt, response.data))

        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Wrong123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 423, response.data)

    @patch("users.views.verify_email_otp", side_effect=OtpInvalid)
    def test_fifth_wrong_otp_verification_locks_account_for_fifteen_minutes_fr_p1_03(self, verify_otp):
        for attempt in range(1, 5):
            response = self.client.post(
                "/api/v1/auth/verify-otp/",
                {"identifier": self.user.email, "otp": "000000"},
                format="json",
            )
            self.assertEqual(response.status_code, 400, (attempt, response.data))

        response = self.client.post(
            "/api/v1/auth/verify-otp/",
            {"identifier": self.user.email, "otp": "000000"},
            format="json",
        )

        self.assertEqual(response.status_code, 423, response.data)
        self.assertGreaterEqual(response.data["remaining_seconds"], 899)
        self.assertLessEqual(response.data["remaining_seconds"], 900)
        self.assertEqual(verify_otp.call_count, 5)
        self.assertGreaterEqual(response.data["remaining_seconds"], 899)
        self.assertLessEqual(response.data["remaining_seconds"], 900)

        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 423, response.data)

    def test_locked_login_uses_v1_account_locked_envelope_fr_p1_03_gnfr_04(self):
        from .models import UserSecurityProfile

        profile = UserSecurityProfile.objects.create(
            user=self.user,
            failed_attempts=5,
            locked_until=timezone.now() + timedelta(minutes=15),
        )

        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        body = response.json()

        self.assertEqual(response.status_code, 423)
        self.assertEqual(body["error"]["code"], "account_locked")
        self.assertIn("temporarily locked", body["error"]["message"])
        self.assertGreater(body["error"]["details"]["remaining_seconds"], 0)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_passwords_use_the_production_hasher_nfr_p1_01(self):
        user = get_user_model().objects.create_user(
            username="production-hasher@example.com",
            email="production-hasher@example.com",
            password="Valid123!",
        )

        self.assertTrue(user.password.startswith("pbkdf2_"))

    def test_phone_identifier_login_uses_the_security_profile(self):
        from .models import UserSecurityProfile

        UserSecurityProfile.objects.create(user=self.user, phone="+919876543210")

        response = self.client.post(
            "/api/v1/auth/login/",
            {"identifier": "+919876543210", "password": "Valid123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("token", response.data)

    def test_inactive_session_is_rejected_server_side(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        token = response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        from .models import UserSession

        session = UserSession.objects.get(user=self.user)
        session.last_activity_at = timezone.now() - timedelta(minutes=31)
        session.save(update_fields=["last_activity_at"])

        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, 401, response.data)

    def test_logout_revokes_server_session(self):
        """GNFR-04: versioned 204 responses are represented as enveloped 200 responses."""
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        token = response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        self.assertEqual(self.client.post("/api/v1/auth/logout/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_reset_password_revokes_existing_sessions_and_allows_new_password(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        old_token = response.data["token"]
        uid = __import__("django.utils.http", fromlist=["urlsafe_base64_encode"]).urlsafe_base64_encode(
            __import__("django.utils.encoding", fromlist=["force_bytes"]).force_bytes(self.user.pk)
        )
        reset_token = default_token_generator.make_token(self.user)

        response = self.client.post(
            "/api/v1/auth/reset-password/",
            {"uid": uid, "token": reset_token, "new_password": "NewValid123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
        self.client.credentials()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "NewValid123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_change_password_revokes_existing_sessions(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "password": "Valid123!"},
            format="json",
        )
        old_token = response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")

        response = self.client.post(
            "/api/v1/auth/change-password/",
            {"old_password": "Valid123!", "new_password": "Changed123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
