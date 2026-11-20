from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.test import override_settings
from rest_framework.test import APITestCase
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission
from organizations.services import ensure_default_roles, has_permission
from .audit import log_audit
from .models import AuditLog, IntegrationConfiguration, SystemParameter
from users.models import DeveloperAccount


class SettingsApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(username="root", email="root@example.test", password="password123")
        self.platform = User.objects.create_user(username="platform", email="platform@example.test", password="password123")
        Group.objects.create(name="Platform Admin").user_set.add(self.platform)
        self.admin = User.objects.create_user(username="admin", email="admin@example.test", password="password123")
        self.manager = User.objects.create_user(username="manager", email="manager@example.test", password="password123")
        self.member = User.objects.create_user(username="member", email="member@example.test", password="password123")
        self.org = Organization.objects.create(name="Org A", slug="org-a")
        ensure_default_roles(self.org)
        self.admin_member = OrganizationMembership.objects.create(organization=self.org, user=self.admin, role="admin")
        self.manager_membership = OrganizationMembership.objects.create(organization=self.org, user=self.manager, role="manager")
        self.member_membership = OrganizationMembership.objects.create(organization=self.org, user=self.member, role="telecaller")

    def test_platform_access_is_not_organization_admin_access(self):
        self.client.force_authenticate(self.superuser)
        self.assertEqual(self.client.get("/api/settings/overview/").status_code, 200)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/settings/overview/").status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/settings/overview/").status_code, 401)

    def test_v1_audit_logs_is_developer_only_and_supports_search(self):
        AuditLog.objects.create(
            organization=self.org,
            user=self.admin,
            module="users",
            action="user_updated",
            ip_address="127.0.0.1",
            details={"fields": ["email"]},
        )
        self.client.force_authenticate(self.platform)
        self.assertEqual(self.client.get("/api/v1/audit-logs/", {"search": "user_updated"}).status_code, 403)
        DeveloperAccount.objects.create(user=self.platform)

        response = self.client.get("/api/v1/audit-logs/", {"search": "user_updated"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["user"]["email"], self.admin.email)
        self.assertEqual(response.data["results"][0]["details"], {"fields": ["email"]})

    @override_settings(DJANGO_TRUST_PROXY=True)
    def test_explicit_audit_row_uses_trusted_forwarded_client_address_gnfr_14(self):
        request = RequestFactory().post(
            "/api/organizations/org-a/settings/general/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.40",
        )
        request.user = self.admin

        row = log_audit(
            request=request,
            organization=self.org,
            module="settings",
            action="explicit_test",
        )

        self.assertEqual(row.ip_address, "198.51.100.40")

    def test_audit_rows_are_immutable_and_expose_phase3_fields(self):
        row = AuditLog.objects.create(
            organization=self.org,
            user=self.admin,
            module="users",
            action="user_updated",
            method="PUT",
            route="/api/v1/organizations/org-a/users/1/",
            payload_before={"first_name": "before"},
            payload_after={"first_name": "after"},
        )
        with self.assertRaises(Exception):
            AuditLog.objects.filter(pk=row.pk).delete()
        with self.assertRaises(Exception):
            row.action = "tampered"
            row.save(update_fields=["action"])

    def test_general_settings_and_isolation(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch("/api/organizations/org-a/settings/general/", {"timezone": "UTC", "items_per_page": 50}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["timezone"], "UTC")
        self.assertEqual(self.client.patch("/api/organizations/missing/settings/general/", {"timezone": "UTC"}, format="json").status_code, 404)

    @override_settings(INTEGRATION_ENCRYPTION_KEY="")
    def test_missing_key_rejects_secret_storage(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post("/api/organizations/org-a/settings/integrations/", {"integration_type": "sms", "name": "SMS", "secrets": {"api_key": "secret"}, "confirmation": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(IntegrationConfiguration.objects.count(), 0)

    def test_secret_is_encrypted_and_not_returned_or_audited(self):
        key = Fernet.generate_key().decode()
        with override_settings(INTEGRATION_ENCRYPTION_KEY=key):
            self.client.force_authenticate(self.admin)
            response = self.client.post("/api/organizations/org-a/settings/integrations/", {"integration_type": "sms", "name": "SMS", "secrets": {"api_key": "secret"}, "confirmation": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("secrets", response.data)
        self.assertNotIn("secret", IntegrationConfiguration.objects.get().encrypted_secrets)
        self.assertNotIn("api_key", str(AuditLog.objects.last().details))

    def test_critical_parameter_requires_confirmation(self):
        self.client.force_authenticate(self.admin)
        payload = {"category": "business_rules", "parameter_key": "lead-followup-days", "parameter_name": "Lead followup", "value": 3, "data_type": "integer", "is_critical": True}
        self.assertEqual(self.client.post("/api/organizations/org-a/settings/system-parameters/", payload, format="json").status_code, 409)
        payload["confirmation"] = True
        self.assertEqual(self.client.post("/api/organizations/org-a/settings/system-parameters/", payload, format="json").status_code, 201)

    def test_canonical_role_controls_permission(self):
        self.assertTrue(self.member_membership.organization_role_id)
        self.assertTrue(has_permission(self.admin, self.org, "settings.edit"))
        self.assertFalse(has_permission(self.member, self.org, "settings.edit"))

    def test_manager_can_view_organization_settings_but_needs_edit_permission_to_manage_roles(self):
        self.assertTrue(has_permission(self.manager, self.org, "settings.view"))
        self.assertFalse(has_permission(self.manager, self.org, "settings.edit"))

        self.client.force_authenticate(self.manager)
        overview_response = self.client.get("/api/organizations/org-a/settings/overview/")
        self.assertEqual(overview_response.status_code, 200, overview_response.data)
        self.assertEqual(overview_response.data["organization_slug"], "org-a")
        settings_response = self.client.get("/api/organizations/org-a/settings/general/")
        self.assertEqual(settings_response.status_code, 200, settings_response.data)

        role_response = self.client.post(
            "/api/organizations/org-a/roles/",
            {"name": "Manager Attempt", "code": "manager-attempt", "permission_ids": []},
            format="json",
        )
        self.assertEqual(role_response.status_code, 403, role_response.data)

    def test_manager_with_settings_edit_can_create_a_role(self):
        settings_edit = Permission.objects.get(module="settings", action="edit")
        self.manager_membership.organization_role.permissions.add(settings_edit)
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            "/api/organizations/org-a/roles/",
            {"name": "Expense Reviewer", "code": "expense-reviewer", "permission_ids": []},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["code"], "expense-reviewer")
