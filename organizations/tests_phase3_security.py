from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from expenses.models import ExpenseCategory
from users.models import UserSession
from users.security import token_hash

from .models import Organization, OrganizationMembership, OrganizationRole, Permission


class Phase3RevocationTests(TestCase):
    """FR-P3-05, EC-P3-01 and NFR-P3-03 security checks."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="revocation-user@example.test",
            email="revocation-user@example.test",
            password="Valid123!",
        )
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        role_a = OrganizationRole.objects.create(organization=self.org_a, name="A viewer", code="a-viewer")
        role_b = OrganizationRole.objects.create(organization=self.org_b, name="B viewer", code="b-viewer")
        view = Permission.objects.get_or_create(module="dashboard", action="view", defaults={"name": "View dashboard"})[0]
        role_a.permissions.add(view)
        role_b.permissions.add(view)
        self.member_a = OrganizationMembership.objects.create(organization=self.org_a, user=self.user, role="telecaller", organization_role=role_a)
        self.member_b = OrganizationMembership.objects.create(organization=self.org_b, user=self.user, role="telecaller", organization_role=role_b)
        token = Token.objects.create(user=self.user)
        UserSession.objects.create(user=self.user, token_hash=token_hash(token.key), expires_at=timezone.now() + timedelta(minutes=30))
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.token = token

    def test_deactivation_in_one_organization_blocks_that_org_only(self):
        self.member_a.is_active = False
        self.member_a.save(update_fields=["is_active"])
        denied = self.client.get(f"/api/v1/organizations/{self.org_a.slug}/permissions/")
        allowed = self.client.get(f"/api/v1/organizations/{self.org_b.slug}/permissions/")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_no_active_membership_revokes_token_and_returns_401(self):
        OrganizationMembership.objects.filter(user=self.user).update(is_active=False)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(UserSession.objects.filter(user=self.user, revoked_at__isnull=True).exists())
        self.assertFalse(Token.objects.filter(pk=self.token.pk).exists())


class Phase3ExportRevocationTests(TestCase):
    def test_revoking_export_blocks_the_next_export_request(self):
        user = get_user_model().objects.create_user(username="export-user@example.test", email="export-user@example.test", password="Valid123!")
        organization = Organization.objects.create(name="Export Org", slug="export-org")
        role = OrganizationRole.objects.create(organization=organization, name="Export role", code="export-role")
        export_permission = Permission.objects.get_or_create(module="reports", action="export", defaults={"name": "Export reports"})[0]
        role.permissions.add(export_permission)
        OrganizationMembership.objects.create(organization=organization, user=user, role="telecaller", organization_role=role)
        client = APIClient()
        client.force_authenticate(user=user)

        first = client.get("/api/v1/reports/export/")
        self.assertEqual(first.status_code, 200)
        role.permissions.remove(export_permission)
        second = client.get("/api/v1/reports/export/")
        self.assertEqual(second.status_code, 403)
