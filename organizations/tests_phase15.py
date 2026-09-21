from datetime import date, datetime, time, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import EmployeeLeaveBalance, LeaveRequest, Organization, OrganizationMembership, PerformanceReview


class Phase15HrmsTests(TestCase):
    """FR-P15-03/04, EC-P15-01, NFR-P15-01/02 backend acceptance tests."""

    def setUp(self):
        User = get_user_model()
        self.manager_user = User.objects.create_user(username="p15-manager", email="p15-manager@example.com", password="password123")
        self.employee_user = User.objects.create_user(username="p15-employee", email="p15-employee@example.com", password="password123")
        self.organization = Organization.objects.create(name="P15 Org", slug="p15-org")
        self.manager = OrganizationMembership.objects.create(organization=self.organization, user=self.manager_user, role=OrganizationMembership.Role.MANAGER, employee_id="MGR-15", first_name="Manager")
        self.employee = OrganizationMembership.objects.create(organization=self.organization, user=self.employee_user, role=OrganizationMembership.Role.TELECALLER, employee_id="EMP-15", first_name="Employee", reporting_manager=self.manager, shift_start_time=time(9), shift_end_time=time(18))
        self.client = APIClient(); self.client.force_authenticate(self.employee_user)

    def test_overlapping_leave_is_rejected_without_duplicate_row(self):
        url = reverse("leave-list", args=[self.organization.slug])
        payload = {"employee": self.employee.id, "leave_type": "casual", "from_date": "2026-10-05", "to_date": "2026-10-07", "reason": "Personal"}
        first = self.client.post(url, payload, format="json")
        second = self.client.post(url, {**payload, "from_date": "2026-10-07", "to_date": "2026-10-09"}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 400, second.data)
        self.assertEqual(LeaveRequest.objects.count(), 1)

    def test_approved_leave_deducts_balance(self):
        balance = EmployeeLeaveBalance.objects.create(organization=self.organization, employee=self.employee, leave_type=EmployeeLeaveBalance.LeaveType.CASUAL, allocated_days=10)
        leave = LeaveRequest.objects.create(organization=self.organization, employee=self.employee, leave_type=LeaveRequest.LeaveType.CASUAL, from_date=date(2026, 10, 5), to_date=date(2026, 10, 7), days=3, reason="Personal")
        self.client.force_authenticate(self.manager_user)
        response = self.client.post(reverse("leave-approve", args=[self.organization.slug, leave.id]), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        balance.refresh_from_db()
        self.assertEqual(balance.used_days, 3)
        self.assertEqual(balance.remaining_days, 7)

    def test_working_hours_are_calculated_from_check_in_and_out(self):
        from .hr_services import check_in, check_out
        checked_in = datetime(2026, 10, 1, 9, 0, tzinfo=dt_timezone.utc)
        checked_out = datetime(2026, 10, 1, 17, 30, tzinfo=dt_timezone.utc)
        check_in(organization=self.organization, employee=self.employee, actor=self.employee_user, when=checked_in)
        record = check_out(organization=self.organization, employee=self.employee, actor=self.employee_user, when=checked_out)
        self.assertEqual(record.total_hours.total_seconds(), 8.5 * 3600)

    def test_manager_can_submit_quarterly_review_but_employee_cannot(self):
        url = reverse("performance-review-list", args=[self.organization.slug])
        denied = self.client.post(url, {"employee": self.employee.id, "quarter": "2026-Q4", "rating": 4, "comments": "Good"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.manager_user)
        created = self.client.post(url, {"employee": self.employee.id, "quarter": "2026-Q4", "rating": 4, "comments": "Good"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(PerformanceReview.objects.count(), 1)
