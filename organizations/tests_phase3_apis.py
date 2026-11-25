from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership, OrganizationRole, Permission
from .services import ensure_default_roles
from users.models import DeveloperAccount


class Phase3ScopedApiContractTests(TestCase):
    """API-P3-01..07 and G-2 contract checks."""

    def setUp(self):
        self.organization = Organization.objects.create(name="API contract org", slug="api-contract-org")
        roles = ensure_default_roles(self.organization)
        self.user = get_user_model().objects.create_user(username="api-user@example.test", email="api-user@example.test", password="Valid123!")
        restricted_role = OrganizationRole.objects.create(organization=self.organization, name="Restricted", code="restricted")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role="telecaller",
            organization_role=restricted_role,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_users_get_requires_users_manage_after_employee_view(self):
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/users/")
        self.assertEqual(response.status_code, 403)
        permission = Permission.objects.get(module="employees", action="view")
        roles = self.membership.organization_role
        roles.permissions.add(permission)
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/users/")
        self.assertEqual(response.status_code, 403)
        roles.permissions.add(Permission.objects.get(module="users", action="manage"))
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/users/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_roles_get_requires_role_view_and_post_requires_role_add(self):
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/roles/")
        self.assertEqual(response.status_code, 403)
        role = self.membership.organization_role
        role.permissions.add(Permission.objects.get(module="role", action="view"))
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/roles/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_role_permissions_put_route_replaces_permissions_and_locks_admin(self):
        role = OrganizationRole.objects.create(organization=self.organization, name="Custom", code="custom")
        role.permissions.add(Permission.objects.get(module="role", action="view"))
        self.membership.organization_role.permissions.add(*Permission.objects.filter(module="role"))
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/roles/{role.id}/permissions/",
            {"permission_ids": [Permission.objects.get(module="role", action="edit").id]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(role.permissions.values_list("action", flat=True)), ["edit"])

        admin = OrganizationRole.objects.get(organization=self.organization, code="admin")
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/roles/{admin.id}/permissions/",
            {"permission_ids": []},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "system_role_locked")

    def test_organization_audit_route_is_developer_only(self):
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/audit-logs/")
        self.assertEqual(response.status_code, 403)
        DeveloperAccount.objects.create(user=self.user)
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/audit-logs/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
