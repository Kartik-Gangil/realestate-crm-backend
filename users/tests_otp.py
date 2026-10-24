from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class FirebaseEmailOtpApiTests(TestCase):
    """FR-P1-01, NFR-P1-02, EC-P1-01, API-P1-01 and API-P1-02."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="asha@example.com",
            email="asha@example.com",
            password="Valid123!",
        )
        self.client = APIClient()

    @patch("users.otp.send_mail")
    @patch("users.otp._otp_reference")
    def test_request_otp_stores_only_a_hash_and_sends_email(self, reference_factory, send_mail):
        reference = Mock()
        reference.data = None
        reference.transaction.side_effect = lambda callback: setattr(reference, "data", callback(reference.data)) or reference.data
        reference_factory.return_value = reference
        send_mail.return_value = 1

        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": self.user.email, "mode": "otp"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "If an active account uses this email address, an OTP has been sent.")
        payload = reference.data
        self.assertIn("otp_hash", payload)
        self.assertNotIn("otp", payload)
        reference.transaction.assert_called_once()
        send_mail.assert_called_once()
        self.assertIn("Your login OTP is", send_mail.call_args.args[1])

    @patch("users.otp.send_mail")
    @patch("users.otp._otp_reference")
    def test_fourth_request_in_ten_minutes_is_rate_limited(self, reference_factory, send_mail):
        reference = Mock()
        reference.data = {"window_started_at": 1_800_000_000, "request_count": 3}
        reference.transaction.side_effect = lambda callback: callback(reference.data)
        reference_factory.return_value = reference

        with patch("users.otp.time.time", return_value=1_800_000_100):
            response = self.client.post(
                "/api/v1/auth/login/",
                {"email": self.user.email, "mode": "otp"},
                format="json",
            )

        self.assertEqual(response.status_code, 429)
        send_mail.assert_not_called()

    @patch("users.otp._otp_reference")
    def test_successful_verification_returns_existing_drf_response(self, reference_factory):
        reference = Mock()
        reference.transaction.side_effect = lambda callback: callback(reference.data)
        reference.data = {
            "otp_hash": "",
            "expires_at": 1_900_000_000,
            "attempts": 0,
            "used": False,
        }
        reference_factory.return_value = reference

        with patch("users.otp.check_password", return_value=True), patch("users.otp.time.time", return_value=1_800_000_000):
            response = self.client.post(
                "/api/v1/auth/verify-otp/",
                {"identifier": self.user.email, "otp": "123456"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["user"]["email"], self.user.email)
        self.assertTrue(reference.data["used"])

    @patch("users.otp._otp_reference")
    def test_invalid_or_expired_otp_does_not_issue_a_token(self, reference_factory):
        reference = Mock()
        reference.transaction.side_effect = lambda callback: callback(reference.data)
        reference.data = {
            "otp_hash": "stored-hash",
            "expires_at": 1_700_000_000,
            "attempts": 0,
            "used": False,
        }
        reference_factory.return_value = reference

        with patch("users.otp.time.time", return_value=1_800_000_000):
            response = self.client.post(
                "/api/v1/auth/verify-otp/",
                {"identifier": self.user.email, "otp": "123456"},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("token", response.data)

    @patch("users.otp._otp_reference")
    def test_realtime_database_failure_returns_retryable_error(self, reference_factory):
        reference = Mock()
        reference.transaction.side_effect = RuntimeError("database unavailable")
        reference_factory.return_value = reference

        response = self.client.post(
            "/api/v1/auth/verify-otp/",
            {"identifier": self.user.email, "otp": "123456"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("token", response.data)

    @override_settings(
        FIREBASE_PROJECT_ID="project",
        FIREBASE_CLIENT_EMAIL="service-account@example.com",
        FIREBASE_PRIVATE_KEY="private-key",
        FIREBASE_DATABASE_URL="https://console.firebase.google.com/u/0/project/project/database/project-default-rtdb/data",
    )
    @patch("users.otp.firebase_admin.initialize_app")
    @patch("users.otp.credentials.Certificate")
    @patch("users.otp.firebase_admin.get_app", side_effect=ValueError)
    def test_console_url_is_rejected_before_admin_initialization(self, get_app, certificate, initialize_app):
        from users.otp import FirebaseOtpStorageUnavailable, _firebase_app

        with self.assertRaises(FirebaseOtpStorageUnavailable):
            _firebase_app()

        certificate.assert_not_called()
        initialize_app.assert_not_called()
