from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Department, Organization, OrganizationActivity, OrganizationMembership, OrganizationRole, Permission


class EmployeeApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="admin@example.com", email="admin@example.com", password="password123")
        self.manager = user_model.objects.create_user(username="manager@example.com", email="manager@example.com", password="password123")
        self.viewer = user_model.objects.create_user(username="viewer@example.com", email="viewer@example.com", password="password123")
        self.other_user = user_model.objects.create_user(username="other@example.com", email="other@example.com", password="password123")
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.other_org = Organization.objects.create(name="Other", slug="other")
        self.admin_membership = OrganizationMembership.objects.create(organization=self.org, user=self.admin, role="admin", employee_id="EMP0001")
        self.manager_membership = OrganizationMembership.objects.create(organization=self.org, user=self.manager, role="manager", employee_id="EMP0002")
        self.viewer_membership = OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role="telecaller", employee_id="EMP0003")
        self.other_membership = OrganizationMembership.objects.create(organization=self.other_org, user=self.other_user, role="manager", employee_id="EMP0001")
        self.department = Department.objects.create(organization=self.org, name="Sales")
        self.other_department = Department.objects.create(organization=self.other_org, name="Other Sales")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def employees_url(self):
        return reverse("employee-list", args=[self.org.slug])

    def v1_users_url(self):
        return f"/api/v1/organizations/{self.org.slug}/users/"

    def v1_user_detail_url(self, employee):
        return f"{self.v1_users_url()}{employee.id}/"

    def v1_user_status_url(self, employee, action):
        return f"{self.v1_user_detail_url(employee)}{action}/"

    def detail_url(self, employee):
        return reverse("employee-detail", args=[self.org.slug, employee.id])

    def create_payload(self, **overrides):
        payload = {
            "email": "new.employee@example.com", "temporary_password": "temporary-pass-123",
            "first_name": "New", "last_name": "Employee", "role": "telecaller",
            "department": self.department.id, "designation": "Site Executive", "mobile_number": "9999999999",
        }
        payload.update(overrides)
        return payload

    def test_unauthenticated_employee_api_is_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.employees_url()).status_code, 401)

    def test_v1_user_directory_route_returns_organization_users(self):
        response = self.client.get(self.v1_users_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual({item["email"] for item in response.data["results"]}, {
            self.admin.email,
            self.manager.email,
            self.viewer.email,
        })

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.v1_users_url()).status_code, 401)

    def test_v1_user_update_and_status_routes_persist_changes(self):
        response = self.client.put(
            self.v1_user_detail_url(self.manager_membership),
            {
                "first_name": "Updated",
                "last_name": "Manager",
                "mobile_number": "9999999999",
                "designation": "Sales Lead",
                "role": "manager",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.manager_membership.refresh_from_db()
        self.assertEqual(self.manager_membership.first_name, "Updated")
        self.assertEqual(self.manager_membership.designation, "Sales Lead")

        response = self.client.post(self.v1_user_status_url(self.manager_membership, "deactivate"))
        self.assertEqual(response.status_code, 200, response.data)
        self.manager_membership.refresh_from_db()
        self.assertFalse(self.manager_membership.is_active)

    def test_v1_user_update_persists_canonical_role_assignment_and_effective_permissions(self):
        expense_role = OrganizationRole.objects.create(
            organization=self.org,
            name="Expense Reviewer",
            code="expense-reviewer",
        )
        mark_paid, _ = Permission.objects.get_or_create(
            module="expenses",
            action="mark_paid",
            defaults={"name": "Mark expenses as paid"},
        )
        expense_role.permissions.add(mark_paid)

        response = self.client.put(
            self.v1_user_detail_url(self.manager_membership),
            {"role_id": expense_role.id},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.manager_membership.refresh_from_db()
        self.assertEqual(self.manager_membership.organization_role_id, expense_role.id)
        self.assertEqual(response.data["role_id"], expense_role.id)
        self.assertEqual(response.data["role_name"], "Expense Reviewer")

        permissions = self.client.get(
            f"/api/v1/organizations/{self.org.slug}/users/{self.manager_membership.id}/tab-permissions/"
        )
        self.assertEqual(permissions.status_code, 200, permissions.data)
        self.assertEqual(permissions.data["selected_permission_codes"], ["expenses.mark_paid"])

    def test_v1_user_update_rejects_a_role_from_another_organization(self):
        foreign_role = OrganizationRole.objects.create(
            organization=self.other_org,
            name="Foreign Role",
            code="foreign-role",
        )

        response = self.client.put(
            self.v1_user_detail_url(self.manager_membership),
            {"role_id": foreign_role.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.manager_membership.refresh_from_db()
        self.assertIsNone(self.manager_membership.organization_role_id)

    def test_v1_user_update_accepts_settings_fields_and_persists_them(self):
        response = self.client.put(
            self.v1_user_detail_url(self.manager_membership),
            {
                "email": "updated.manager@example.com",
                "department": self.department.name,
                "address": "22 Main Street",
                "date_of_birth": "1990-01-02",
                "shift_start_time": "09:00",
                "shift_end_time": "18:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.manager_membership.refresh_from_db()
        self.manager_membership.user.refresh_from_db()
        self.assertEqual(self.manager_membership.user.email, "updated.manager@example.com")
        self.assertEqual(self.manager_membership.department_id, self.department.id)
        self.assertEqual(self.manager_membership.address, "22 Main Street")
        self.assertEqual(str(self.manager_membership.date_of_birth), "1990-01-02")
        self.assertEqual(str(self.manager_membership.shift_start_time), "09:00:00")
        self.assertEqual(str(self.manager_membership.shift_end_time), "18:00:00")

        response = self.client.put(self.v1_user_detail_url(self.manager_membership), {}, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_v1_user_email_update_does_not_require_a_department(self):
        response = self.client.put(
            self.v1_user_detail_url(self.viewer_membership),
            {"email": "updated.viewer@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.viewer_membership.refresh_from_db()
        self.viewer_membership.user.refresh_from_db()
        self.assertEqual(self.viewer_membership.user.email, "updated.viewer@example.com")
        self.assertIsNone(self.viewer_membership.department_id)

    def test_create_list_search_filter_and_activity(self):
        directory = self.client.get(self.employees_url())
        self.assertEqual(directory.status_code, 200, directory.data)
        admin_row = next(item for item in directory.data["results"] if item["email"] == self.admin.email)
        self.assertEqual(admin_row["user_id"], self.admin.id)

        response = self.client.post(self.employees_url(), self.create_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        employee = OrganizationMembership.objects.get(user__email="new.employee@example.com")
        self.assertEqual(employee.organization, self.org)
        self.assertEqual(employee.employee_id, "EMP0004")
        self.assertTrue(employee.user.check_password("temporary-pass-123"))
        self.assertEqual(OrganizationActivity.objects.filter(employee=employee, action="employee_created").count(), 1)
        response = self.client.get(self.employees_url(), {"search": "Executive", "department": self.department.id, "page_size": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)

    def test_cross_organization_objects_and_employees_are_not_usable(self):
        response = self.client.post(self.employees_url(), self.create_payload(department=self.other_department.id), format="json")
        self.assertEqual(response.status_code, 400)

    def test_employee_list_marks_only_finance_payment_eligible_members(self):
        user_model = get_user_model()
        finance_user = user_model.objects.create_user(username="finance@example.com", email="finance@example.com")
        finance_role = OrganizationRole.objects.create(organization=self.org, name="Finance", code="finance")
        finance_membership = OrganizationMembership.objects.create(
            organization=self.org, user=finance_user, role="finance", organization_role=finance_role, employee_id="EMP0004"
        )

        permission_user = user_model.objects.create_user(username="payment-reviewer@example.com", email="payment-reviewer@example.com")
        payment_role = OrganizationRole.objects.create(
            organization=self.org, name="Payment Reviewer", code="payment-reviewer"
        )
        mark_paid, _ = Permission.objects.get_or_create(
            module="expenses", action="mark_paid", defaults={"name": "Mark expenses as paid"}
        )
        payment_role.permissions.add(mark_paid)
        permission_membership = OrganizationMembership.objects.create(
            organization=self.org, user=permission_user, role="payment-reviewer",
            organization_role=payment_role, employee_id="EMP0005",
        )

        response = self.client.get(self.employees_url())

        self.assertEqual(response.status_code, 200, response.data)
        eligibility = {item["email"]: item["can_process_expense_payment"] for item in response.data["results"]}
        self.assertTrue(eligibility[self.admin.email])
        self.assertTrue(eligibility[self.manager.email])
        self.assertTrue(eligibility[finance_user.email])
        self.assertTrue(eligibility[permission_user.email])
        self.assertFalse(eligibility[self.viewer.email])
        self.assertEqual(finance_membership.employee_id, "EMP0004")
        self.assertEqual(permission_membership.employee_id, "EMP0005")

    def test_employee_create_uses_the_selected_organization_role(self):
        selected_role = OrganizationRole.objects.create(
            organization=self.org, name="Expense Reviewer", code="expense-reviewer"
        )
        payload = self.create_payload()
        payload.pop("role")
        payload["role_id"] = selected_role.id

        response = self.client.post(self.employees_url(), payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        employee = OrganizationMembership.objects.get(user__email="new.employee@example.com")
        self.assertEqual(employee.organization_role_id, selected_role.id)
        self.assertEqual(response.data["role_name"], "Expense Reviewer")
        response = self.client.post(self.employees_url(), self.create_payload(reporting_manager=self.other_membership.id), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.detail_url(self.other_membership)).status_code, 404)

    def test_update_status_lifecycle_and_role_permissions(self):
        employee = OrganizationMembership.objects.create(organization=self.org, user=get_user_model().objects.create_user(username="employee", email="employee@example.com", password="password123"), role="telecaller", employee_id="EMP0100")
        response = self.client.patch(self.detail_url(employee), {"designation": "Senior Executive"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(reverse("employee-deactivate", args=[self.org.slug, employee.id])).status_code, 200)
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)
        self.assertEqual(self.client.post(reverse("employee-activate", args=[self.org.slug, employee.id])).status_code, 200)
        self.assertTrue(OrganizationActivity.objects.filter(employee=employee, action="employee_deactivated", performed_by=self.admin).exists())

        manager_client = APIClient(); manager_client.force_authenticate(self.manager)
        self.assertEqual(manager_client.patch(self.detail_url(employee), {"role": "manager"}, format="json").status_code, 403)
        viewer_client = APIClient(); viewer_client.force_authenticate(self.viewer)
        self.assertEqual(viewer_client.post(self.employees_url(), self.create_payload(email="no@example.com"), format="json").status_code, 403)

    def test_access_scope_limits_employee_visibility(self):
        self.viewer_membership.access_scope = OrganizationMembership.AccessScope.OWN
        self.viewer_membership.save(update_fields=["access_scope"])
        client = APIClient(); client.force_authenticate(self.viewer)
        response = client.get(self.employees_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.viewer_membership.id])


class PasswordResetApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="member@example.com", email="member@example.com", password="old-password-123")
        self.client = APIClient()

    @patch("users.views.send_mail")
    def test_forgot_password_sends_a_link_without_exposing_account_data(self, send_mail):
        response = self.client.post(reverse("users:forgot-password"), {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send_mail.call_count, 1)

    def test_change_password_requires_current_password(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(reverse("users:change-password"), {"old_password": "wrong", "new_password": "new-password-123"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("users:change-password"), {"old_password": "old-password-123", "new_password": "new-password-123"}, format="json").status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-password-123"))
