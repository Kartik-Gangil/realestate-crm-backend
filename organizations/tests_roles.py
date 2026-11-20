from datetime import timedelta
import importlib

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from users.models import UserSession
from users.security import token_hash

from .models import Organization, OrganizationMembership, OrganizationRole, Permission
from .services import ensure_default_roles


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
        token = Token.objects.create(user=self.user)
        UserSession.objects.create(
            user=self.user,
            token_hash=token_hash(token.key),
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

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
        for module in (
            "dashboard", "leads", "assigned_leads", "customers", "telecalling", "follow_ups",
            "site_visits", "plots", "payments", "registry", "loans", "employees", "documents",
            "expenses", "communication", "activity", "reports", "role", "settings",
            "attendance", "leave",
        ):
            expected_actions = ("view", "add", "edit", "delete", "export", "approve")
            self.assertTrue(
                {f"{module}.{action}" for action in expected_actions} <= codes,
                module,
            )

        self.assertIn("plots.view_team", codes)

        for module in ("assigned_leads", "site_visits", "loans"):
            self.assertTrue({f"{module}.{action}" for action in ("view", "add", "edit", "delete", "export")} <= codes)

    def test_default_telecaller_has_read_only_project_inventory_access(self):
        roles = ensure_default_roles(self.organization)
        telecaller = roles["telecaller"]
        permissions = set(telecaller.permissions.values_list("module", "action"))

        self.assertIn(("plots", "view"), permissions)
        self.assertIn(("plots", "view_team"), permissions)
        self.assertFalse(any(module == "plots" and action in {"add", "edit", "delete", "export"} for module, action in permissions))

    def test_default_manager_can_approve_team_expenses(self):
        roles = ensure_default_roles(self.organization)
        permissions = set(roles["manager"].permissions.values_list("module", "action"))

        self.assertIn(("expenses", "view"), permissions)
        self.assertIn(("expenses", "view_team"), permissions)
        self.assertIn(("expenses", "approve"), permissions)
        self.assertIn(("expenses", "reject"), permissions)

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

    def test_permission_update_rejects_malformed_ids_without_server_error(self):
        original_ids = set(self.role.permissions.values_list("id", flat=True))

        response = self.client.patch(
            f"/api/organizations/{self.organization.slug}/roles/{self.role.id}/",
            {"permission_ids": [""]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("permission_ids", response.data)
        self.assertEqual(
            set(self.role.permissions.values_list("id", flat=True)),
            original_ids,
        )

    def test_phase3_permission_catalogue_has_organization_or_project_scope(self):
        """DM-P3-02 / Step 4: every permission declares its tenancy scope."""
        scope = Permission._meta.get_field("scope")
        self.assertEqual(set(scope.choices), {("organization", "Organization"), ("project", "Project")})

    def test_phase3_role_description_round_trips(self):
        """DM-P3-01 / FR-P3-02: role descriptions are persisted and returned."""
        response = self.client.post(
            f"/api/organizations/{self.organization.slug}/roles/",
            {
                "name": "Described role",
                "code": "described-role",
                "description": "Read-only sales access",
                "permission_ids": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["description"], "Read-only sales access")
        self.assertEqual(
            OrganizationRole.objects.get(pk=response.data["id"]).description,
            "Read-only sales access",
        )

    def test_phase3_system_admin_role_is_locked(self):
        """FR-P3-06: renaming or stripping the system Admin returns system_role_locked."""
        self.admin_role.is_system = True
        self.admin_role.save(update_fields=["is_system"])
        response = self.client.patch(
            f"/api/organizations/{self.organization.slug}/roles/{self.admin_role.id}/",
            {"name": "Renamed admin"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "system_role_locked")
        self.assertEqual(
            self.admin_role.__class__.objects.get(pk=self.admin_role.pk).name,
            "Organization admin",
        )

    def test_phase3_ensure_default_roles_repairs_system_role_flags(self):
        """FR-P3-06: Admin is the only system role; templates are editable."""
        roles = ensure_default_roles(self.organization)
        roles["telecaller"].is_system = True
        roles["telecaller"].save(update_fields=["is_system"])
        roles["manager"].is_system = True
        roles["manager"].save(update_fields=["is_system"])
        roles = ensure_default_roles(self.organization)
        self.assertTrue(roles["admin"].is_system)
        self.assertFalse(roles["manager"].is_system)
        self.assertFalse(roles["telecaller"].is_system)

    def test_phase3_admin_role_receives_permissions_added_later(self):
        """FR-P3-06: the system Admin role keeps every newly-created permission."""
        roles = ensure_default_roles(self.organization)
        new_permission = Permission.objects.create(
            module="new_module",
            action="view",
            name="View new module",
        )
        self.assertTrue(roles["admin"].permissions.filter(pk=new_permission.pk).exists())

    def test_phase3_six_standard_actions_allow_and_refuse(self):
        """NFR-P3-01: RBAC boolean evaluation covers all six standard actions."""
        from .services import has_permission

        role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Six action role",
            code="six-action",
        )
        member = OrganizationMembership.objects.create(
            organization=self.organization,
            user=get_user_model().objects.create_user(
                username="six-action-user",
                email="six-action-user@example.com",
                password="password123",
            ),
            role="telecaller",
            organization_role=role,
        )
        permissions = [
            Permission.objects.get_or_create(
                module="leads",
                action=action,
                defaults={"name": f"{action} leads"},
            )[0]
            for action in ("view", "add", "edit", "delete", "export", "approve")
        ]
        for permission in permissions:
            role.permissions.add(permission)
            self.assertTrue(has_permission(member.user, self.organization, permission.code))
            role.permissions.remove(permission)
            self.assertFalse(has_permission(member.user, self.organization, permission.code))

    def test_phase3_permission_migration_merges_legacy_actions_and_employee_module(self):
        """DM-P3-02: migration preserves role rights while normalizing legacy codes."""
        legacy_create = Permission.objects.create(
            module="employee",
            action="create",
            name="Legacy employee create",
        )
        legacy_manage = Permission.objects.create(
            module="documents",
            action="manage",
            name="Legacy document manage",
        )
        legacy_role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Legacy role",
            code="legacy-role",
        )
        legacy_role.permissions.add(legacy_create, legacy_manage)

        migration = importlib.import_module("organizations.migrations.0019_phase3_permissions")
        migration.normalize_legacy_permissions(Permission, OrganizationRole)

        legacy_role.refresh_from_db()
        codes = set(legacy_role.permissions.values_list("module", "action"))
        self.assertIn(("employees", "add"), codes)
        self.assertIn(("documents", "edit"), codes)
        self.assertFalse(Permission.objects.filter(module="employee").exists())
        self.assertFalse(Permission.objects.filter(action="create").exists())
