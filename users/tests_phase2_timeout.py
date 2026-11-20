from datetime import timedelta

from django.test import TestCase
from django.test.client import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization
from organizations.models import OrganizationMembership
from organizations.services import ensure_default_roles
from system_settings.models import SystemParameter
from users.models import UserSession
from users.security import get_session_timeout_minutes, issue_session


class Phase2SessionTimeoutTests(TestCase):
    """FR-P1-04 / DM-P2-03: auth consumes organization auto-logout settings."""

    def test_timeout_uses_shortest_active_organization_setting(self):
        user = make_member(make_organization("timeout-one"), role="admin").user
        second_org = make_organization("timeout-two")
        roles = ensure_default_roles(second_org)
        OrganizationMembership.objects.create(
            organization=second_org, user=user, role="admin", organization_role=roles["admin"]
        )
        SystemParameter.objects.filter(organization__slug="timeout-one", parameter_key="auto_logout_minutes").update(value=45)
        SystemParameter.objects.filter(organization__slug="timeout-two", parameter_key="auto_logout_minutes").update(value=10)

        self.assertEqual(get_session_timeout_minutes(user), 10)

    def test_auth_me_exposes_effective_session_timeout(self):
        membership = make_member(make_organization("timeout-me"), role="admin")
        user = membership.user
        SystemParameter.objects.filter(organization=membership.organization, parameter_key="auto_logout_minutes").update(value=12)
        client = APIClient()
        token = issue_session(user, RequestFactory().get("/api/v1/auth/login/"))
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()["data"]["session_timeout_minutes"], 12)
