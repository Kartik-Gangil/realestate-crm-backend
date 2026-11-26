"""Attached UAT report regressions for LC-12, LC-13 and LC-18."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project

from .hr_services import ensure_leave_balance
from .models import AttendanceRecord, LeaveRequest
from .services import ensure_default_roles


class UatLcOrganizationTests(TestCase):
    """Existing HR/employee flows remain intact while missing permissions are restored."""

    def setUp(self):
        self.organization = make_organization("uat-lc-org")
        self.project = make_project(self.organization, "LCORG")
        self.employee = make_member(self.organization, role="telecaller", projects=[self.project])
        self.hr_admin = make_member(self.organization, role="hr-admin", projects=[self.project])
        self.roles = ensure_default_roles(self.organization)

    def test_employee_roles_have_self_service_attendance_and_leave_permissions_lc12(self):
        for role_code in ("telecaller", "site-visit-executive", "accounts"):
            role = self.roles[role_code]
            self.assertTrue(
                role.permissions.filter(module="attendance", action__in=["view", "add", "edit"]).count() >= 3,
                role_code,
            )
            self.assertTrue(
                role.permissions.filter(module="leave", action__in=["view", "add", "edit"]).count() >= 3,
                role_code,
            )

    def test_hr_admin_can_cancel_an_employee_leave_lc13(self):
        leave = LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type="casual",
            from_date=date(2026, 12, 1),
            to_date=date(2026, 12, 1),
            days=1,
            reason="UAT cancellation",
        )
        client = APIClient()
        client.force_authenticate(self.hr_admin.user)

        response = client.post(
            f"/api/v1/organizations/{self.organization.slug}/leaves/{leave.pk}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        leave.refresh_from_db()
        self.assertEqual(leave.status, LeaveRequest.Status.CANCELLED)

    def test_attendance_payload_keeps_full_employee_name_lc18(self):
        self.employee.user.first_name = "Asha"
        self.employee.user.last_name = "Sharma"
        self.employee.user.save(update_fields=["first_name", "last_name"])
        AttendanceRecord.objects.create(
            organization=self.organization,
            employee=self.employee,
            attendance_date=date(2026, 11, 26),
            status=AttendanceRecord.Status.PRESENT,
        )
        client = APIClient()
        client.force_authenticate(self.hr_admin.user)

        response = client.get(f"/api/v1/organizations/{self.organization.slug}/attendance/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["employee"]["name"], "Asha Sharma")

    def test_leave_without_from_date_returns_field_validation_rt03(self):
        client = APIClient()
        client.force_authenticate(self.employee.user)

        response = client.post(
            f"/api/v1/organizations/{self.organization.slug}/leaves/",
            {"to_date": "2026-12-01", "leave_type": "casual", "reason": "UAT"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("from_date", response.data)
        self.assertNotEqual(response.data.get("detail"), "'from_date'")
