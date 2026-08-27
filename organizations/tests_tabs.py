from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Organization, OrganizationMembership, OrganizationRole, Permission


class RoleDerivedTabPermissionsTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="agent", email="agent@example.com", password="password123")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.role = OrganizationRole.objects.create(organization=self.organization, name="Lead agent", code="lead-agent")
        dashboard, _ = Permission.objects.get_or_create(module="dashboard", action="view", defaults={"name": "View dashboard"})
        leads, _ = Permission.objects.get_or_create(module="leads", action="view", defaults={"name": "View leads"})
        self.role.permissions.set([dashboard, leads])
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role="telecaller",
            organization_role=self.role,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def test_response_derives_tabs_from_role_permissions(self):
        response = self.client.get("/api/organizations/acme/my-tab-permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], "lead-agent")
        self.assertEqual(response.data["permissions"], ["dashboard.view", "leads.view"])

    def test_role_permission_changes_update_tabs_for_assigned_user(self):
        admin = get_user_model().objects.create_user(username="admin", email="admin@example.com", password="password123")
        admin_role = OrganizationRole.objects.create(organization=self.organization, name="Administrator", code="administrator")
        admin_role.permissions.set(Permission.objects.all())
        OrganizationMembership.objects.create(
            organization=self.organization, user=admin, role="admin", organization_role=admin_role,
        )
        self.role.permissions.remove(Permission.objects.get(module="dashboard", action="view"))
        response = self.client.get("/api/organizations/acme/my-tab-permissions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["permissions"], ["leads.view"])
