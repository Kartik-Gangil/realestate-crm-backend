from datetime import timedelta
import io
import importlib

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from organizations.services import ensure_default_roles

from .models import UserSession
from .security import token_hash


class SessionLifecycleTests(TestCase):
    """FR-P1-06, DM-P1-02 and FR-P3-05 session lifecycle acceptance tests."""

    PASSWORD = "Valid123!"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="session-owner@example.com",
            email="session-owner@example.com",
            password=self.PASSWORD,
        )
        organization = Organization.objects.create(name="Session Org", slug="session-org")
        role = ensure_default_roles(organization)["manager"]
        OrganizationMembership.objects.create(
            organization=organization, user=self.user, role="manager", organization_role=role
        )

    def login(self, client=None, password=None):
        client = client or APIClient()
        response = client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": password or self.PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["token"]

    def me(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return client.get("/api/auth/me/")

    def test_logout_deletes_token_forever_and_next_login_rotates_it_fr_p1_06_dm_p1_02(self):
        client = APIClient()
        token = self.login(client)
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        self.assertEqual(client.post("/api/auth/logout/").status_code, 204)
        self.assertFalse(Token.objects.filter(key=token).exists())
        self.assertEqual(self.me(token).status_code, 401)

        new_token = self.login()
        self.assertNotEqual(new_token, token)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.me(new_token).status_code, 200)

    def test_two_logins_share_one_token_until_logout_fr_p1_06_dm_p1_02(self):
        first_token = self.login()
        second_token = self.login()

        self.assertEqual(second_token, first_token)
        self.assertEqual(Token.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.me(first_token).status_code, 200)
        self.assertEqual(self.me(second_token).status_code, 200)

    def test_token_without_session_is_rejected_without_auto_creation_fr_p1_06_dm_p1_02(self):
        token = Token.objects.create(user=self.user).key

        self.assertEqual(self.me(token).status_code, 401)
        self.assertFalse(UserSession.objects.filter(token_hash=token_hash(token)).exists())

    @override_settings(AUTH_SESSION_TIMEOUT_MINUTES=30)
    def test_expired_or_idle_session_is_rejected_and_revoked_fr_p1_04_dm_p1_02(self):
        token = self.login()
        session = UserSession.objects.get(token_hash=token_hash(token))
        session.last_activity_at = timezone.now() - timedelta(minutes=31)
        session.save(update_fields=["last_activity_at"])

        self.assertEqual(self.me(token).status_code, 401)
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at)

    def test_deactivated_user_token_is_rejected_on_the_next_request_fr_p3_05(self):
        token = self.login()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        self.assertEqual(self.me(token).status_code, 401)

    def test_user_with_no_active_organization_membership_cannot_login_fr_p3_05(self):
        self.user.organization_memberships.update(is_active=False)

        response = APIClient().post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 401, response.data)
        self.assertNotIn("token", response.data)

    def test_change_password_deletes_token_and_revokes_sessions_fr_p1_06_dm_p1_02(self):
        token = self.login()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        response = client.post(
            "/api/auth/change-password/",
            {"old_password": self.PASSWORD, "new_password": "Changed123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Token.objects.filter(key=token).exists())
        self.assertEqual(UserSession.objects.filter(user=self.user, revoked_at__isnull=True).count(), 0)
        self.assertEqual(self.me(token).status_code, 401)

    def test_reset_password_deletes_token_and_revokes_sessions_fr_p1_06_dm_p1_02(self):
        token = self.login()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        reset_token = default_token_generator.make_token(self.user)

        response = APIClient().post(
            "/api/auth/reset-password/",
            {"uid": uid, "token": reset_token, "new_password": "Reset123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Token.objects.filter(key=token).exists())
        self.assertEqual(UserSession.objects.filter(user=self.user, revoked_at__isnull=True).count(), 0)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.login(password="Reset123!"), self.login(password="Reset123!"))

    def test_session_ip_uses_the_same_trusted_proxy_rule_as_rate_limit_gnfr_14_dm_p1_02(self):
        with override_settings(DJANGO_TRUST_PROXY=False):
            self.login_client_with_ip("192.0.2.10", "198.51.100.1, 198.51.100.9")
        self.assertEqual(UserSession.objects.get(user=self.user).ip_address, "192.0.2.10")

        UserSession.objects.all().delete()
        Token.objects.all().delete()
        with override_settings(DJANGO_TRUST_PROXY=True):
            self.login_client_with_ip("192.0.2.11", "198.51.100.1, 198.51.100.9")
        self.assertEqual(UserSession.objects.get(user=self.user).ip_address, "198.51.100.9")

    def login_client_with_ip(self, remote_addr, forwarded_for):
        response = APIClient().post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.PASSWORD},
            format="json",
            REMOTE_ADDR=remote_addr,
            HTTP_X_FORWARDED_FOR=forwarded_for,
        )
        self.assertEqual(response.status_code, 200, response.data)


class RevokeAllTokensTests(TestCase):
    """FR-P1-06 / DM-P1-02: global token revocation never exposes token values."""

    def test_revoke_all_tokens_deletes_tokens_revokes_sessions_and_reports_counts_fr_p1_06_dm_p1_02(self):
        user_model = get_user_model()
        users = [
            user_model.objects.create_user(username=f"revoke-{index}@example.com", password="Valid123!")
            for index in range(2)
        ]
        token_keys = []
        for user in users:
            token = Token.objects.create(user=user)
            token_keys.append(token.key)
            UserSession.objects.create(
                user=user,
                token_hash=token_hash(token.key),
                expires_at=timezone.now() + timedelta(minutes=30),
            )

        output = io.StringIO()
        call_command("revoke_all_tokens", "--yes", stdout=output)

        self.assertEqual(Token.objects.count(), 0)
        self.assertEqual(UserSession.objects.filter(revoked_at__isnull=True).count(), 0)
        self.assertIn("2 tokens", output.getvalue())
        self.assertIn("2 sessions", output.getvalue())
        for token_key in token_keys:
            self.assertNotIn(token_key, output.getvalue())


class SessionCleanupMigrationTests(TransactionTestCase):
    """FR-P1-06 / DM-P1-02: stale token cleanup migration is exercised explicitly."""

    def test_cleanup_migration_deletes_revoked_expired_and_missing_session_tokens_fr_p1_06_dm_p1_02(self):
        now = timezone.now()
        fixtures = []
        for index, revoked_at, expires_at in (
            ("valid", None, now + timedelta(minutes=30)),
            ("revoked", now, now + timedelta(minutes=30)),
            ("expired", None, now - timedelta(minutes=1)),
            ("missing", None, None),
        ):
            user = get_user_model().objects.create_user(
                username=f"migration-cleanup-{index}@example.com", password="Valid123!"
            )
            token = Token.objects.create(user=user)
            fixtures.append((index, token))
            if expires_at is not None:
                UserSession.objects.create(
                    user=user,
                    token_hash=token_hash(token.key),
                    expires_at=expires_at,
                    revoked_at=revoked_at,
                )

        migration = importlib.import_module("users.migrations.0002_cleanup_stale_tokens")

        class Apps:
            @staticmethod
            def get_model(app_label, model_name):
                if app_label == "authtoken" and model_name == "Token":
                    return Token
                if app_label == "users" and model_name == "UserSession":
                    return UserSession
                raise AssertionError((app_label, model_name))

        migration.delete_stale_tokens(Apps(), None)

        for name, token in fixtures:
            self.assertEqual(Token.objects.filter(key=token.key).exists(), name == "valid")
