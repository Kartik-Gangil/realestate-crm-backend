from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from system_settings.models import AuditLog

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, Project


class Phase3RbacAndUserAdministrationTests(TestCase):
    """PHASE 3: FR-P3-01..FR-P3-07 and API-P3-01..API-P3-07."""

    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="admin@phase3.test", email="admin@phase3.test", password="Valid-password-1!"
        )
        self.employee_user = user_model.objects.create_user(
            username="employee@phase3.test", email="employee@phase3.test", password="Valid-password-1!"
        )
        self.organization = Organization.objects.create(name="Phase 3 Realty", slug="phase3-realty")
        self.project_a = Project.objects.create(organization=self.organization, name="Project A", code="P3-A")
        self.project_b = Project.objects.create(organization=self.organization, name="Project B", code="P3-B")
        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN
        )
        self.employee = OrganizationMembership.objects.create(
            organization=self.organization, user=self.employee_user, role=OrganizationMembership.Role.TELECALLER
        )
        self.view_permission, _ = Permission.objects.get_or_create(
            module="reports", action="view", defaults={"name": "View reports"}
        )
        self.export_permission, _ = Permission.objects.get_or_create(
            module="reports", action="export", defaults={"name": "Export reports"}
        )
        self.settings_edit, _ = Permission.objects.get_or_create(
            module="settings", action="edit", defaults={"name": "Edit settings"}
        )
        self.role = OrganizationRole.objects.create(
            organization=self.organization, name="Reports operator", code="reports-operator"
        )
        self.role.permissions.set([self.view_permission, self.export_permission, self.settings_edit])
        self.employee.organization_role = self.role
        self.employee.save(update_fields=["organization_role"])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def role_url(self, role=None):
        return f"/api/v1/organizations/{self.organization.slug}/roles/{(role or self.role).id}/"

    def employees_url(self):
        return f"/api/v1/organizations/{self.organization.slug}/employees/"

    def test_fr_p3_01_user_project_scope_is_created_and_returned(self):
        response = self.client.post(
            self.employees_url(),
            {
                "email": "new-user@phase3.test",
                "temporary_password": "Valid-password-1!",
                "first_name": "New",
                "role": "telecaller",
                "project_ids": [self.project_a.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        created = OrganizationMembership.objects.get(user__email="new-user@phase3.test")
        self.assertEqual(list(created.projects.values_list("id", flat=True)), [self.project_a.id])
        self.assertEqual(response.data["project_ids"], [self.project_a.id])

    def test_fr_p3_02_and_api_p3_06_custom_role_permission_matrix_is_audited(self):
        response = self.client.patch(
            self.role_url(),
            {"permission_ids": [self.view_permission.id]},
            format="json",
            REMOTE_ADDR="203.0.113.44",
        )

        self.assertEqual(response.status_code, 200, response.data)
        audit = AuditLog.objects.get(module="roles", action="role_updated", target_id=str(self.role.id))
        self.assertEqual(audit.ip_address, "203.0.113.44")
        self.assertEqual(
            set(audit.details["payload_before"]["permissions"]),
            {"reports.export", "reports.view", "settings.edit"},
        )
        self.assertEqual(audit.details["payload_after"]["permissions"], ["reports.view"])

    def test_fr_p3_06_system_role_cannot_be_deleted_or_stripped(self):
        system_role = OrganizationRole.objects.create(
            organization=self.organization, name="System role", code="system-role", is_system=True
        )
        system_role.permissions.set([self.view_permission, self.export_permission])

        strip_response = self.client.patch(
            self.role_url(system_role), {"permission_ids": [self.view_permission.id]}, format="json"
        )
        delete_response = self.client.delete(self.role_url(system_role), {"confirmation": True}, format="json")

        self.assertEqual(strip_response.status_code, 409)
        self.assertEqual(delete_response.status_code, 409)
        self.assertTrue(OrganizationRole.objects.filter(pk=system_role.pk).exists())

    def test_fr_p3_05_deactivated_user_cannot_use_existing_token(self):
        employee_url = f"/api/v1/organizations/{self.organization.slug}/employees/{self.employee.id}/deactivate/"
        response = self.client.post(employee_url)
        self.assertEqual(response.status_code, 200, response.data)
        self.employee_user.refresh_from_db()
        self.assertFalse(self.employee_user.is_active)

        blocked_client = APIClient()
        blocked_client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.employee_user).key}",
            HTTP_X_PROJECT_ID=self.project_a.code,
        )
        self.assertEqual(
            blocked_client.get(f"/api/v1/organizations/{self.organization.slug}/roles/").status_code,
            401,
        )

    def test_ec_p3_01_revoked_permission_blocks_next_protected_request(self):
        self.client.force_authenticate(self.employee_user)
        allowed = self.client.patch(self.role_url(), {"name": "Reports operator"}, format="json")
        self.assertEqual(allowed.status_code, 200)

        self.client.force_authenticate(self.admin)
        self.role.permissions.remove(self.settings_edit)
        self.client.force_authenticate(self.employee_user)
        blocked = self.client.patch(self.role_url(), {"name": "Should fail"}, format="json")
        self.assertEqual(blocked.status_code, 403)
