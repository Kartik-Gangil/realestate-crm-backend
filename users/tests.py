from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import UserSession
from .otp import OTP_TTL_SECONDS, store_otp, verify_otp


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_RESET_FRONTEND_URL="http://frontend.test/reset-password",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fr-p1-05-tests",
        }
    },
)
class PasswordResetFlowTests(TestCase):
    """FR-P1-05: verify the complete email reset-token workflow."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="reset-user@example.com",
            email="reset-user@example.com",
            password="Old-password-1!",
        )

    def _reset_link_params(self):
        self.assertEqual(len(mail.outbox), 1)
        reset_url = next(
            word for word in mail.outbox[0].body.split() if word.startswith("http://frontend.test/")
        )
        query = parse_qs(urlparse(reset_url).query)
        return query["uid"][0], query["token"][0]

    def test_forgot_password_email_token_resets_password_end_to_end(self):
        forgot_response = self.client.post(
            reverse("users_v1:forgot-password"),
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(forgot_response.status_code, 200)
        self.assertIn("sent", forgot_response.data["detail"])
        uid, token = self._reset_link_params()

        reset_response = self.client.post(
            reverse("users_v1:reset-password"),
            {"uid": uid, "token": token, "new_password": "New-password-2!"},
            format="json",
        )

        self.assertEqual(reset_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-password-2!"))

    def test_unknown_email_returns_same_success_response_without_sending_email(self):
        response = self.client.post(
            reverse("users_v1:forgot-password"),
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("sent", response.data["detail"])
        self.assertEqual(mail.outbox, [])

    def test_reset_requires_uid_token_and_new_password(self):
        response = self.client.post(
            reverse("users_v1:reset-password"),
            {"uid": "", "token": "", "new_password": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("required", response.data["detail"])

    def test_invalid_or_expired_token_is_rejected(self):
        with patch("users.views.default_token_generator.check_token", return_value=False):
            response = self.client.post(
                reverse("users_v1:reset-password"),
                {"uid": "MQ", "token": "expired-token", "new_password": "New-password-2!"},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid or has expired", str(response.data))

    def test_reset_token_cannot_be_reused_after_password_change(self):
        self.client.post(
            reverse("users_v1:forgot-password"),
            {"email": self.user.email},
            format="json",
        )
        uid, token = self._reset_link_params()
        payload = {"uid": uid, "token": token, "new_password": "New-password-2!"}

        first_response = self.client.post(reverse("users_v1:reset-password"), payload, format="json")
        second_response = self.client.post(reverse("users_v1:reset-password"), payload, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        self.assertIn("invalid or has expired", str(second_response.data))


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fr-p1-06-tests",
        }
    }
)
class SessionInvalidationTests(TestCase):
    """FR-P1-06 / DM-P1-02: logout revokes the token and tracked session."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="session-user@example.com",
            email="session-user@example.com",
            password="Valid-password-1!",
        )

    def test_login_tracks_hashed_session_metadata(self):
        response = self.client.post(
            reverse("users_v1:login"),
            {"email": self.user.email, "password": "Valid-password-1!"},
            format="json",
            REMOTE_ADDR="203.0.113.10",
            HTTP_USER_AGENT="FR-P1-06 test client",
        )

        self.assertEqual(response.status_code, 200)
        token = response.data["token"]
        session = UserSession.objects.get(user=self.user)
        self.assertNotEqual(session.token_hash, token)
        self.assertEqual(session.ip_address, "203.0.113.10")
        self.assertEqual(session.user_agent, "FR-P1-06 test client")
        self.assertTrue(session.expires_at)

    def test_logout_revokes_token_and_tracked_session(self):
        login_response = self.client.post(
            reverse("users_v1:login"),
            {"email": self.user.email, "password": "Valid-password-1!"},
            format="json",
            REMOTE_ADDR="203.0.113.10",
        )
        token = login_response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        logout_response = self.client.post(reverse("users_v1:logout"), {}, format="json")

        self.assertEqual(logout_response.status_code, 204)
        self.assertFalse(UserSession.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.get(reverse("users_v1:me")).status_code, 401)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fr-p1-07-tests",
        }
    }
)
class AuthenticationRouteRestrictionTests(TestCase):
    """FR-P1-07: unauthenticated users only reach auth entry/reset routes."""

    def setUp(self):
        self.client = APIClient()

    def test_unauthenticated_user_can_reach_login_and_password_reset_routes(self):
        login_response = self.client.post(
            reverse("users_v1:login"),
            {"email": "unknown@example.com", "password": "wrong-password"},
            format="json",
        )
        forgot_response = self.client.post(
            reverse("users_v1:forgot-password"),
            {"email": "unknown@example.com"},
            format="json",
        )
        reset_response = self.client.post(
            reverse("users_v1:reset-password"),
            {},
            format="json",
        )

        self.assertEqual(login_response.status_code, 400)
        self.assertEqual(forgot_response.status_code, 200)
        self.assertEqual(reset_response.status_code, 400)

    def test_unauthenticated_user_cannot_reach_registration_or_protected_routes(self):
        register_response = self.client.post(
            reverse("users_v1:register"),
            {
                "email": "new-user@example.com",
                "password": "Valid-password-1!",
            },
            format="json",
        )
        me_response = self.client.get(reverse("users_v1:me"))
        logout_response = self.client.post(reverse("users_v1:logout"), {}, format="json")
        change_password_response = self.client.post(
            reverse("users_v1:change-password"),
            {"old_password": "old", "new_password": "Valid-password-1!"},
            format="json",
        )

        self.assertEqual(register_response.status_code, 401)
        self.assertEqual(me_response.status_code, 401)
        self.assertEqual(logout_response.status_code, 401)
        self.assertEqual(change_password_response.status_code, 401)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fr-p1-02-tests",
        }
    }
)
class PasswordHashAndOtpStorageTests(TestCase):
    """NFR-P1-01 / NFR-P1-02: secure password and OTP storage."""

    def tearDown(self):
        cache.clear()

    def test_new_passwords_use_argon2_hashes(self):
        user = get_user_model().objects.create_user(
            username="argon-user@example.com",
            email="argon-user@example.com",
            password="Valid-password-1!",
        )

        self.assertTrue(user.password.startswith("argon2$"))
        self.assertNotIn("Valid-password-1!", user.password)

    def test_otp_is_hashed_in_cache_with_ttl_and_is_one_time(self):
        account_key = "user:otp@example.com"
        otp = "123456"

        store_otp(account_key, otp)
        stored_value = cache.get(f"users:otp:{account_key}")

        self.assertIsNotNone(stored_value)
        self.assertNotEqual(stored_value, otp)
        self.assertEqual(verify_otp(account_key, otp), True)
        self.assertEqual(verify_otp(account_key, otp), False)

    @patch("users.otp.cache.set")
    def test_otp_storage_uses_required_ttl(self, cache_set):
        store_otp("user:ttl@example.com", "654321")

        cache_set.assert_called_once()
        self.assertEqual(cache_set.call_args.kwargs["timeout"], OTP_TTL_SECONDS)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fr-p1-03-lockout-tests",
        }
    }
)
class AccountLockoutSecurityTests(TestCase):
    """NFR-P1-03 / FR-P1-03: failed-login lockout integration coverage."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username="locked-user@example.com",
            email="locked-user@example.com",
            password="Valid-password-1!",
        )

    def tearDown(self):
        cache.clear()

    def test_fifth_consecutive_failed_login_returns_423_locked(self):
        responses = [
            self.client.post(
                reverse("users_v1:login"),
                {"email": self.user.email, "password": "wrong-password"},
                format="json",
            )
            for _ in range(5)
        ]

        self.assertEqual([response.status_code for response in responses[:4]], [400] * 4)
        self.assertEqual(responses[4].status_code, 423)
        self.assertIn("locked", str(responses[4].data).lower())

    def test_login_during_lockout_returns_remaining_lock_time(self):
        for _ in range(5):
            self.client.post(
                reverse("users_v1:login"),
                {"email": self.user.email, "password": "wrong-password"},
                format="json",
            )

        response = self.client.post(
            reverse("users_v1:login"),
            {"email": self.user.email, "password": "Valid-password-1!"},
            format="json",
        )

        self.assertEqual(response.status_code, 423)
        self.assertRegex(str(response.data), r"\d+ seconds")
