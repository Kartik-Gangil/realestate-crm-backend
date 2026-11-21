from datetime import date, datetime, time
from io import StringIO

from django.core.management import call_command
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from system_settings.models import AuditLog, SystemParameter
from system_settings.parameters import PARAMETER_REGISTRY
from system_settings.services import ensure_organization_parameter_defaults, validate_parameter_value
from core.models import Notification

from .hr_services import check_in, check_out, ensure_leave_balance, leave_days
from .models import (
    AttendanceRecord,
    LeaveBalance,
    LeaveRequest,
    OrganizationHoliday,
    OrganizationMembership,
    PerformanceReview,
)
from .permission_catalogue import ALLOWED_NAMED_PERMISSION_REQUIREMENTS
from .services import ensure_default_roles


class GroupEPhase15Tests(TestCase):
    """Phase 15 / FR-P15-01..06, DM-P15-04 and NFR-P15-01..02."""

    def setUp(self):
        self.organization = make_organization("group-e-p15")
        self.project = make_project(self.organization, "P15")
        self.employee_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.employee_membership.reporting_manager = self.manager_membership
        self.employee_membership.salary = 50000
        self.employee_membership.save(update_fields=["reporting_manager", "salary"])
        roles = ensure_default_roles(self.organization)
        self.hr_membership = make_member(self.organization, role="hr-admin", projects=[self.project])
        self.employee = self.employee_membership.user
        self.manager = self.manager_membership.user
        self.admin = self.admin_membership.user
        self.hr_admin = self.hr_membership.user
        self.employee_client = APIClient()
        self.manager_client = APIClient()
        self.hr_client = APIClient()
        self.employee_client.force_authenticate(self.employee)
        self.manager_client.force_authenticate(self.manager)
        self.hr_client.force_authenticate(self.hr_admin)

        # The employee is allowed to use the own-record attendance/leave APIs.
        permissions = []
        for code in ("attendance.view", "attendance.add", "attendance.edit", "leave.view", "leave.add", "leave.edit"):
            module, action = code.split(".")
            permission = self.employee_membership.organization_role.permissions.filter(module=module, action=action).first()
            if permission is None:
                from .models import Permission

                permission, _ = Permission.objects.get_or_create(
                    module=module, action=action, defaults={"name": code}
                )
            permissions.append(permission)
        self.employee_membership.organization_role.permissions.add(*permissions)

    def leave_url(self):
        return f"/api/v1/organizations/{self.organization.slug}/leaves/"

    def leave_balances_url(self):
        return f"/api/v1/organizations/{self.organization.slug}/leave-balances/"

    def performance_url(self, employee_id):
        return f"/api/v1/organizations/{self.organization.slug}/performance/{employee_id}/"

    def employee_url(self, employee_id):
        return f"/api/v1/organizations/{self.organization.slug}/employees/{employee_id}/"

    def test_fr_p15_02_working_day_counts_monday_through_saturday_and_excludes_holiday(self):
        OrganizationHoliday.objects.create(
            organization=self.organization, name="Republic Day", holiday_date=date(2026, 1, 3)
        )
        self.assertEqual(leave_days(self.organization, date(2026, 1, 1), date(2026, 1, 7)), 5)

    def test_ui_p15_04_employee_can_read_current_leave_balances(self):
        response = self.employee_client.get(self.leave_balances_url())

        self.assertEqual(response.status_code, 200, response.data)
        casual = next(item for item in response.data["results"] if item["leave_type"] == "casual")
        self.assertEqual(casual["employee"]["id"], self.employee_membership.id)
        self.assertEqual(casual["allocated_days"], 12)
        self.assertEqual(casual["used_days"], 0)
        self.assertEqual(casual["remaining_days"], 12)

    def test_nfr_p15_01_server_calculates_total_hours_and_refuses_double_check_in(self):
        start = timezone.make_aware(datetime(2026, 1, 5, 9, 0))
        finish = timezone.make_aware(datetime(2026, 1, 5, 17, 30))
        check_in(organization=self.organization, employee=self.employee_membership, actor=self.employee, when=start)
        with self.assertRaises(ValidationError):
            check_in(organization=self.organization, employee=self.employee_membership, actor=self.employee, when=start)
        record = check_out(
            organization=self.organization, employee=self.employee_membership, actor=self.employee, when=finish
        )
        self.assertEqual(record.total_hours.total_seconds(), 8.5 * 3600)
        self.assertEqual(record.status, AttendanceRecord.Status.PRESENT)

    def test_fr_p15_03_first_leave_use_creates_balance_and_overlap_or_insufficient_balance_creates_no_row(self):
        response = self.employee_client.post(
            self.leave_url(),
            {"leave_type": "paid", "from_date": "2026-02-02", "to_date": "2026-02-03", "reason": "Family work"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(LeaveBalance.objects.filter(employee=self.employee_membership, year=2026, leave_type="paid").exists())
        before = LeaveRequest.objects.count()
        overlap = self.employee_client.post(
            self.leave_url(),
            {"leave_type": "paid", "from_date": "2026-02-03", "to_date": "2026-02-04", "reason": "Overlap"},
            format="json",
        )
        self.assertEqual(overlap.status_code, 400, overlap.data)
        self.assertEqual(LeaveRequest.objects.count(), before)
        balance = ensure_leave_balance(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="casual",
            year=2026,
        )
        balance.allocated_days = 1
        balance.save(update_fields=["allocated_days"])
        insufficient = self.employee_client.post(
            self.leave_url(),
            {"leave_type": "casual", "from_date": "2026-02-09", "to_date": "2026-02-10", "reason": "Too long"},
            format="json",
        )
        self.assertEqual(insufficient.status_code, 400, insufficient.data)
        self.assertEqual(LeaveRequest.objects.count(), before)

    def test_fr_p15_06_only_reporting_manager_or_hr_admin_can_approve_and_cancel_restores_balance(self):
        leave = LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="casual",
            from_date=date(2026, 3, 2),
            to_date=date(2026, 3, 3),
            days=2,
            reason="Approved leave",
        )
        balance = ensure_leave_balance(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="casual",
            year=2026,
        )
        balance.allocated_days = 10
        balance.save(update_fields=["allocated_days"])
        wrong = make_member(self.organization, role="manager", projects=[self.project])
        wrong_client = APIClient()
        wrong_client.force_authenticate(wrong.user)
        denied = wrong_client.post(f"{self.leave_url()}{leave.id}/approve/", {}, format="json")
        self.assertEqual(denied.status_code, 403, denied.data)
        approved = self.manager_client.post(f"{self.leave_url()}{leave.id}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        balance.refresh_from_db()
        self.assertEqual(balance.used_days, 2)
        self.assertEqual(balance.remaining_days, 8)
        duplicate = self.manager_client.post(f"{self.leave_url()}{leave.id}/approve/", {}, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.employee_client.post(f"{self.leave_url()}{leave.id}/cancel/", {}, format="json")
        balance.refresh_from_db()
        self.assertEqual(balance.used_days, 0)

    def test_g0_leave_decision_creates_pending_in_app_notification(self):
        leave = LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="casual",
            from_date=date(2026, 3, 9),
            to_date=date(2026, 3, 9),
            days=1,
            reason="Appointment",
        )
        balance = ensure_leave_balance(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="casual",
            year=2026,
        )
        balance.allocated_days = 10
        balance.save(update_fields=["allocated_days"])

        response = self.manager_client.post(f"{self.leave_url()}{leave.id}/approve/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        notification = Notification.objects.get(
            recipient_membership=self.employee_membership,
            type="leave_decision",
            related_object_id=leave.id,
        )
        self.assertEqual(notification.status, Notification.Status.PENDING)
        self.assertIn("approved", notification.title.lower())

    def test_fr_p15_01_salary_is_hidden_without_compensation_permission(self):
        hidden = self.employee_client.get(self.employee_url(self.employee_membership.id))
        self.assertEqual(hidden.status_code, 200, hidden.data)
        self.assertNotIn("salary", hidden.data)
        visible = APIClient()
        visible.force_authenticate(self.admin)
        response = visible.get(self.employee_url(self.employee_membership.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["salary"], "50000.00")

    def test_dm_p15_04_reviews_validate_quarter_and_rating_and_audit_edits(self):
        first = self.manager_client.post(
            self.performance_url(self.employee_membership.id),
            {"quarter": "2026-Q1", "rating": 4, "comments": "Good progress"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        duplicate = self.manager_client.post(
            self.performance_url(self.employee_membership.id),
            {"quarter": "2026-Q1", "rating": 5, "comments": "Duplicate"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        invalid = self.manager_client.post(
            self.performance_url(self.employee_membership.id),
            {"quarter": "2026-Q2", "rating": 6, "comments": "Invalid"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)
        review = PerformanceReview.objects.get(employee=self.employee_membership, quarter="2026-Q1")
        edited = self.manager_client.patch(
            self.performance_url(self.employee_membership.id), {"review_id": review.id, "comments": "Updated"}, format="json"
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertTrue(AuditLog.objects.filter(module="performance_reviews", target_id=str(review.id)).exists())

    def test_group_e_roles_and_leave_parameters_are_provisioned_for_existing_organizations(self):
        roles = ensure_default_roles(self.organization)
        self.assertIn("hr-admin", roles)
        self.assertIn("accounts", roles)
        self.assertTrue(roles["hr-admin"].permissions.filter(module="employees", action="view_compensation").exists())
        self.assertTrue(roles["accounts"].permissions.filter(module="expenses", action="reimburse").exists())
        ensure_organization_parameter_defaults(self.organization)
        for key, default in {
            "leave_casual_days_per_year": 12,
            "leave_sick_days_per_year": 6,
            "leave_paid_days_per_year": 15,
        }.items():
            self.assertEqual(
                SystemParameter.objects.get(
                    organization=self.organization,
                    project__isnull=True,
                    parameter_key=key,
                ).value,
                default,
            )
            self.assertEqual(validate_parameter_value(key, 60), 60)
            with self.assertRaises(DRFValidationError):
                validate_parameter_value(key, 61)
        self.assertEqual(ALLOWED_NAMED_PERMISSION_REQUIREMENTS["employees.view_compensation"], "FR-P15-01")

    def test_task_group_e_earned_to_paid_migration_supports_dry_run(self):
        leave = LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee_membership,
            leave_type="earned",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 1),
            days=1,
            reason="Legacy",
        )
        dry_run = StringIO()
        call_command("migrate_earned_leave", "--dry-run", stdout=dry_run)
        leave.refresh_from_db()
        self.assertEqual(leave.leave_type, "earned")
        self.assertIn("1", dry_run.getvalue())
        call_command("migrate_earned_leave", stdout=StringIO())
        leave.refresh_from_db()
        self.assertEqual(leave.leave_type, "paid")

