"""G-8 / BUG-02 authorization tests for UAT-D03 and UAT-D09."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership, OrganizationRole, Permission
from .services import ensure_default_roles


class Bug02AuthorizationTests(TestCase):
    """FR-P3-01, DM-P3-02, FR-P2-02, and FR-P2-04 acceptance tests."""

    def setUp(self):
        self.organization = Organization.objects.create(name="BUG-02 org", slug="bug-02-org")
        self.roles = ensure_default_roles(self.organization)
        self.client = APIClient()

        self.manager = self._member("manager@example.test", "manager")
        self.admin = self._member("admin@example.test", "admin")
        self.hr_admin = self._member("hr@example.test", "hr-admin")
        self.target = self._member("target@example.test", "telecaller")

    def _member(self, email, role):
        user = get_user_model().objects.create_user(username=email, email=email, password="Valid123!")
        return OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            role=role,
            organization_role=self.roles[role],
        )

    def _url(self, suffix):
        return f"/api/v1/organizations/{self.organization.slug}/{suffix}"

    def test_users_manage_is_named_and_assigned_to_admin_and_hr_admin_templates(self):
        permission = Permission.objects.filter(module="users", action="manage").first()
        self.assertIsNotNone(permission)
        self.assertTrue(self.roles["admin"].permissions.filter(pk=permission.pk).exists())
        self.assertTrue(self.roles["hr-admin"].permissions.filter(pk=permission.pk).exists())

    def test_manager_is_denied_users_routes_but_employee_directory_remains_available(self):
        """GNFR-05 / FR-P15-06 [UAT-D47]: employees.view is separate from users.manage."""
        self.client.force_authenticate(self.manager.user)
        user_base = self._url("users")

        self.assertEqual(self.client.get(f"{user_base}/").status_code, 403)
        self.assertEqual(self.client.get(f"{user_base}/{self.target.pk}/").status_code, 403)
        self.assertEqual(self.client.post(f"{user_base}/", {}, format="json").status_code, 403)
        self.assertEqual(
            self.client.patch(f"{user_base}/{self.target.pk}/", {"first_name": "Changed"}, format="json").status_code,
            403,
        )
        self.assertEqual(self.client.post(f"{user_base}/{self.target.pk}/activate/").status_code, 403)
        self.assertEqual(self.client.post(f"{user_base}/{self.target.pk}/deactivate/").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"{user_base}/{self.target.pk}/reset-password/",
                {"temporary_password": "NewValid123!"},
                format="json",
            ).status_code,
            403,
        )

        employee_response = self.client.get(self._url("employees/"))
        self.assertEqual(employee_response.status_code, 200, employee_response.data)

    def test_admin_and_hr_admin_can_read_users(self):
        for member in (self.admin, self.hr_admin):
            self.client.force_authenticate(member.user)
            response = self.client.get(self._url("users/"))
            self.assertEqual(response.status_code, 200, response.data)

    def test_manager_can_read_company_profile_but_cannot_write_or_view_admin_settings(self):
        self.client.force_authenticate(self.manager.user)
        self.assertEqual(self.client.get(self._url("settings/general/")).status_code, 200)
        self.assertEqual(
            self.client.patch(self._url("settings/general/"), {"company_name": "Blocked"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.client.put(self._url("settings/general/"), {"company_name": "Blocked"}, format="json").status_code,
            403,
        )
        for endpoint in ("settings/system-parameters/", "settings/masters/", "settings/integrations/"):
            self.assertEqual(self.client.get(self._url(endpoint)).status_code, 403, endpoint)

    def test_organization_admin_can_read_and_write_company_profile_and_admin_settings(self):
        self.client.force_authenticate(self.admin.user)
        self.assertEqual(self.client.get(self._url("settings/general/")).status_code, 200)
        self.assertEqual(
            self.client.patch(self._url("settings/general/"), {"company_name": "Updated"}, format="json").status_code,
            200,
        )
        for endpoint in ("settings/system-parameters/", "settings/masters/", "settings/integrations/"):
            self.assertEqual(self.client.get(self._url(endpoint)).status_code, 200, endpoint)
