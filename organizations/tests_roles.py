from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Organization, OrganizationMembership, OrganizationRole, Permission


class RolePermissionUpdateTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="role-admin",
            email="role-admin@example.com",
            password="password123",
        )
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.admin_role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Organization admin",
            code="admin",
        )
        settings_edit, _ = Permission.objects.get_or_create(
            module="settings",
            action="edit",
            defaults={"name": "Edit settings"},
        )
        leads_view, _ = Permission.objects.get_or_create(
            module="leads",
            action="view",
            defaults={"name": "View leads"},
        )
        self.settings_edit = settings_edit
        self.leads_view = leads_view
        self.admin_role.permissions.add(settings_edit)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role="admin",
            organization_role=self.admin_role,
        )
        self.role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Sales",
            code="sales",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def test_permission_update_returns_and_persists_selected_permission_ids(self):
        response = self.client.patch(
            f"/api/organizations/{self.organization.slug}/roles/{self.role.id}/",
            {"permission_ids": [self.leads_view.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["permission_ids"], [self.leads_view.id])
        self.assertEqual(response.data["permissions"], [self.leads_view.code])
        self.assertEqual(
            list(self.role.permissions.values_list("id", flat=True)),
            [self.leads_view.id],
        )
        fresh_read = self.client.get(
            f"/api/organizations/{self.organization.slug}/roles/{self.role.id}/"
        )
        self.assertEqual(fresh_read.status_code, 200)
        self.assertEqual(fresh_read.data["permission_ids"], [self.leads_view.id])

    def test_permission_catalogue_contains_all_frontend_matrix_modules(self):
        response = self.client.get(f"/api/organizations/{self.organization.slug}/permissions/")

        self.assertEqual(response.status_code, 200)
        codes = {item["code"] for item in response.data}
        for module in ("assigned_leads", "site_visits", "loans"):
            self.assertTrue({f"{module}.{action}" for action in ("view", "add", "edit", "delete", "export")} <= codes)

    def test_admin_can_assign_expense_reject_and_mark_paid_permissions(self):
        response = self.client.get(f"/api/organizations/{self.organization.slug}/permissions/")

        self.assertEqual(response.status_code, 200)
        permissions = {item["code"]: item["id"] for item in response.data}
        self.assertIn("expenses.reject", permissions)
        self.assertIn("expenses.mark_paid", permissions)

        updated = self.client.patch(
            f"/api/organizations/{self.organization.slug}/roles/{self.role.id}/",
            {"permission_ids": [permissions["expenses.reject"], permissions["expenses.mark_paid"]]},
            format="json",
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(
            set(updated.data["permissions"]),
            {"expenses.reject", "expenses.mark_paid"},
        )
