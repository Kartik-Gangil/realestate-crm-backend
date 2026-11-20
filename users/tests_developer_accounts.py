from contextlib import redirect_stdout
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from organizations.models import Organization, OrganizationMembership
from inventory.models import Project
from organizations.services import has_permission
from organizations.services import ensure_default_roles
from system_settings.models import AuditLog

from .models import DeveloperAccount, UserSession
from .security import is_developer, token_hash


class DeveloperAccountCommandTests(TestCase):
    """FR-P3-08/09 and Step 5: Developer accounts are command-only."""

    def test_command_creates_developer_and_audits_platform_action(self):
        with patch("getpass.getpass", return_value="Developer-password-123!"):
            call_command("developer_account", "create", "--email", "developer@example.test")

        user = get_user_model().objects.get(email="developer@example.test")
        self.assertTrue(is_developer(user))
        row = AuditLog.objects.get(action="developer_created")
        self.assertIsNone(row.organization_id)
        self.assertIsNone(row.user_id)
        self.assertEqual(row.route, "command:developer_account")

    def test_command_removes_developer_and_audits_platform_action(self):
        user = get_user_model().objects.create_user(
            username="developer@example.test",
            email="developer@example.test",
            password="Developer-password-123!",
        )
        DeveloperAccount.objects.create(user=user)

        call_command("developer_account", "remove", "--email", "developer@example.test")

        self.assertFalse(DeveloperAccount.objects.filter(user=user).exists())
        row = AuditLog.objects.get(action="developer_removed")
        self.assertIsNone(row.organization_id)
        self.assertIsNone(row.user_id)
        self.assertEqual(row.route, "command:developer_account")

    def test_command_list_prints_count_only(self):
        output = StringIO()
        with redirect_stdout(output):
            call_command("developer_account", "list")
        self.assertEqual(output.getvalue().strip(), "Developers: 0")
        self.assertNotIn("@", output.getvalue())

    def test_command_reads_password_file_without_printing_password(self):
        password = "Developer-password-123!"
        temporary_directory = Path(__file__).resolve().parents[1] / ".test-temp"
        temporary_directory.mkdir(exist_ok=True)
        password_path = temporary_directory / "developer-password.txt"
        try:
            password_path.write_text(password, encoding="utf-8")
            output = StringIO()
            call_command(
                "developer_account",
                "create",
                "--email",
                "developer-file@example.test",
                "--password-file",
                str(password_path),
                stdout=output,
            )
        finally:
            password_path.unlink(missing_ok=True)

        user = get_user_model().objects.get(email="developer-file@example.test")
        self.assertTrue(user.check_password(password))
        self.assertNotIn(password, output.getvalue())
        self.assertTrue(AuditLog.objects.filter(action="developer_created").exists())

    def test_command_missing_password_file_stops_with_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "developer_account",
                "create",
                "--email",
                "developer-missing-file@example.test",
                "--password-file",
                "missing-password-file.txt",
            )
        self.assertFalse(
            get_user_model().objects.filter(email="developer-missing-file@example.test").exists()
        )


class DeveloperAccountApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Developer API Org", slug="developer-api-org")
        roles = ensure_default_roles(self.organization)
        self.admin = get_user_model().objects.create_user(
            username="org-admin@example.test",
            email="org-admin@example.test",
            password="Admin-password-123!",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role="admin",
            organization_role=roles["admin"],
        )
        self.developer = get_user_model().objects.create_user(
            username="developer@example.test",
            email="developer@example.test",
            password="Developer-password-123!",
        )
        DeveloperAccount.objects.create(user=self.developer)
        token = Token.objects.create(user=self.admin)
        UserSession.objects.create(
            user=self.admin,
            token_hash=token_hash(token.key),
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_admin_sees_developer_in_user_list_but_not_employee_count(self):
        response = self.client.get(f"/api/v1/organizations/{self.organization.slug}/users/")
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["data"] if isinstance(response.data, dict) and "data" in response.data else response.data
        self.assertEqual(payload["count"], 1)
        self.assertEqual([item["role"] for item in payload["results"]], ["admin"])
        self.assertEqual([item["role"] for item in payload["developers"]], ["Developer"])

    def test_admin_cannot_change_developer_and_api_cannot_set_marker(self):
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/users/{self.developer.id}/",
            {"first_name": "Changed"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        create_response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/users/",
            {
                "email": "normal@example.test",
                "first_name": "Normal",
                "temporary_password": "Normal-password-123!",
                "is_developer": True,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertFalse(DeveloperAccount.objects.filter(user__email="normal@example.test").exists())

    def test_admin_cannot_change_super_admin_and_developer_can_manage_both(self):
        super_admin = get_user_model().objects.create_superuser("super-target", "super-target@example.test", "pw")
        super_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=super_admin,
            role="admin",
            organization_role=ensure_default_roles(self.organization)["admin"],
        )
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/users/{super_membership.pk}/",
            {"first_name": "Blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(self.developer)
        admin_membership = self.admin.organization_memberships.get(organization=self.organization)
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/users/{admin_membership.pk}/",
            {"first_name": "Managed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.put(
            f"/api/v1/organizations/{self.organization.slug}/users/{super_membership.pk}/",
            {"first_name": "Managed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_developer_has_every_permission_in_an_unrelated_organization_and_project(self):
        project = Project.objects.create(organization=self.organization, name="Developer Project", code="DEV-PROJECT")

        self.assertTrue(has_permission(self.developer, self.organization, "plots.export", project=project))

    def test_admin_and_super_admin_cannot_deactivate_role_assign_or_reset_developer(self):
        filler = get_user_model().objects.create_user("filler", "filler@example.test", "pw")
        filler_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=filler,
            role="admin",
            organization_role=ensure_default_roles(self.organization)["admin"],
        )
        filler_membership.delete()
        super_admin = get_user_model().objects.create_superuser("super-target", "super-target@example.test", "pw")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=super_admin,
            role="admin",
            organization_role=ensure_default_roles(self.organization)["admin"],
        )
        admin_role = ensure_default_roles(self.organization)["admin"]
        paths = [
            ("post", f"/api/v1/organizations/{self.organization.slug}/users/{self.developer.id}/deactivate/", {}),
            ("put", f"/api/v1/organizations/{self.organization.slug}/users/{self.developer.id}/", {"role_id": admin_role.pk}),
            ("put", f"/api/v1/organizations/{self.organization.slug}/users/{self.developer.id}/", {"project_ids": []}),
            ("post", f"/api/organizations/{self.organization.slug}/employees/{self.developer.id}/reset-password/", {"temporary_password": "New-password-123!"}),
        ]
        for actor in (self.admin, super_admin):
            self.client.force_authenticate(actor)
            for method, path, payload in paths:
                response = getattr(self.client, method)(path, payload, format="json")
                self.assertEqual(response.status_code, 403, (method, path, response.data))


class DeveloperAdminDeleteProtectionTests(TestCase):
    def test_delete_queryset_and_selected_delete_action_preserve_developer(self):
        from django.contrib import admin
        from users.admin import UserAdmin

        developer = get_user_model().objects.create_user(username="admin-developer", password="pw")
        DeveloperAccount.objects.create(user=developer)
        request = RequestFactory().get("/admin/")
        request.user = get_user_model().objects.create_superuser("admin", "admin@example.test", "pw")
        model_admin = UserAdmin(get_user_model(), admin.site)

        model_admin.delete_queryset(request, get_user_model().objects.filter(pk=developer.pk))

        self.assertTrue(get_user_model().objects.filter(pk=developer.pk).exists())
        self.assertNotIn("delete_selected", model_admin.get_actions(request))

    def test_lower_level_admin_cannot_change_super_admin_in_django_admin(self):
        from django.contrib import admin
        from users.admin import UserAdmin

        actor = get_user_model().objects.create_user(username="organization-admin", password="pw", is_staff=True)
        super_admin = get_user_model().objects.create_superuser("super-admin", "super-admin@example.test", "pw")
        request = RequestFactory().get("/admin/")
        request.user = actor
        model_admin = UserAdmin(get_user_model(), admin.site)

        self.assertFalse(model_admin.has_change_permission(request, super_admin))
        self.assertFalse(model_admin.has_delete_permission(request, super_admin))

