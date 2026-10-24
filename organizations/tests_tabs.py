from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Organization, OrganizationMembership, OrganizationRole, Permission
from .services import effective_tab_permissions, ensure_default_roles


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

    def test_member_tab_permissions_endpoint_returns_role_derived_tabs(self):
        membership = self.role.memberships.first()
        response = self.client.get(f"/api/v1/organizations/acme/users/{membership.id}/tab-permissions/")

        self.assertEqual(response.status_code, 200)
        expected_tabs = ["dashboard", "leads", "assigned_leads", "follow_ups"]
        self.assertEqual(response.data["selected_tab_permissions"], expected_tabs)
        self.assertEqual(response.data["role_allowed_tabs"], expected_tabs)
        self.assertEqual(response.data["effective_tab_permissions"], expected_tabs)

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

    def test_telecaller_role_permissions_expose_telecalling_and_follow_up_tabs(self):
        telecalling, _ = Permission.objects.get_or_create(
            module="telecalling", action="view", defaults={"name": "View telecalling"}
        )
        follow_ups, _ = Permission.objects.get_or_create(
            module="follow_ups", action="view", defaults={"name": "View follow-ups"}
        )
        self.role.permissions.set([telecalling, follow_ups])

        self.assertEqual(
            effective_tab_permissions(self.role.memberships.first()),
            ["follow_ups", "telecalling"],
        )

    def test_default_telecaller_role_does_not_receive_lead_management_permission(self):
        roles = ensure_default_roles(self.organization)

        telecaller_codes = set(roles["telecaller"].permissions.values_list("module", "action"))
        admin_codes = set(roles["admin"].permissions.values_list("module", "action"))

        self.assertNotIn(("leads", "view"), telecaller_codes)
        self.assertNotIn(("leads", "add"), telecaller_codes)
        self.assertNotIn(("leads", "edit"), telecaller_codes)
        self.assertNotIn(("documents", "view"), telecaller_codes)
        self.assertNotIn(("documents", "add"), telecaller_codes)
        self.assertIn(("leads", "view"), admin_codes)
