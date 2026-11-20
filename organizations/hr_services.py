from datetime import datetime, timedelta

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import AttendanceRecord, LeaveBalance, LeaveRequest, OrganizationActivity, OrganizationHoliday
from .services import is_organization_admin
from core.notifications import notify
from system_settings.services import ensure_organization_parameter_defaults, get_system_parameter


def log_activity(*, organization, employee, action, actor, module, details=None):
    """The single audit write path for Phase 2 operations."""
    OrganizationActivity.objects.create(organization=organization, employee=employee, action=action,
                                        module=module, details=details or {}, performed_by=actor)


def attendance_status(employee, checked_in, checked_out=None):
    if not checked_in:
        return AttendanceRecord.Status.INCOMPLETE
    if not employee.shift_start_time:
        return AttendanceRecord.Status.PRESENT
    local_in = timezone.localtime(checked_in)
    return AttendanceRecord.Status.LATE if local_in.time() > employee.shift_start_time else AttendanceRecord.Status.PRESENT


def check_in(*, organization, employee, actor, when=None):
    when = when or timezone.now()
    if employee.organization_id != organization.id:
        raise ValidationError({"employee": "Employee must belong to this organization."})
    date = timezone.localdate(when)
    with transaction.atomic():
        record, created = AttendanceRecord.objects.select_for_update().get_or_create(
            organization=organization, employee=employee, attendance_date=date,
            defaults={"check_in": when, "status": attendance_status(employee, when)},
        )
        if not created:
            if record.check_in:
                raise ValidationError({"attendance": "An attendance record already exists for this employee and date."})
            record.check_in = when
            record.status = attendance_status(employee, when)
            record.save(update_fields=["check_in", "status", "updated_at"])
        log_activity(organization=organization, employee=employee, action="attendance_checked_in", actor=actor,
                     module="attendance", details={"attendance_date": date.isoformat()})
        return record


def check_out(*, organization, employee, actor, when=None):
    when = when or timezone.now()
    date = timezone.localdate(when)
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().filter(
            organization=organization, employee=employee, attendance_date=date).first()
        if not record or not record.check_in:
            raise ValidationError({"attendance": "Check-in is required before check-out."})
        if record.check_out:
            raise ValidationError({"attendance": "This attendance record has already been checked out."})
        if when < record.check_in:
            raise ValidationError({"check_out": "Check-out cannot precede check-in."})
        record.check_out = when
        record.total_hours = when - record.check_in
        record.status = attendance_status(employee, record.check_in, when)
        record.full_clean()
        record.save(update_fields=["check_out", "total_hours", "status", "updated_at"])
        log_activity(organization=organization, employee=employee, action="attendance_checked_out", actor=actor,
                     module="attendance", details={"attendance_date": record.attendance_date.isoformat()})
        return record


def leave_days(organization, from_date, to_date):
    if to_date < from_date:
        raise ValidationError({"to_date": "To date cannot precede from date."})
    holidays = set(OrganizationHoliday.objects.filter(organization=organization, holiday_date__range=(from_date, to_date)).values_list("holiday_date", flat=True))
    return sum(1 for offset in range((to_date - from_date).days + 1)
               if (day := from_date + timedelta(days=offset)).weekday() < 6 and day not in holidays)


LEAVE_PARAMETER_KEYS = {
    LeaveRequest.LeaveType.CASUAL: "leave_casual_days_per_year",
    LeaveRequest.LeaveType.SICK: "leave_sick_days_per_year",
    LeaveRequest.LeaveType.PAID: "leave_paid_days_per_year",
    LeaveRequest.LeaveType.EARNED: "leave_paid_days_per_year",
}


def canonical_leave_type(leave_type):
    return LeaveRequest.LeaveType.PAID if leave_type == LeaveRequest.LeaveType.EARNED else leave_type


def ensure_leave_balance(*, organization, employee, leave_type, year):
    leave_type = canonical_leave_type(leave_type)
    ensure_organization_parameter_defaults(organization)
    parameter_key = LEAVE_PARAMETER_KEYS[leave_type]
    allocated = int(get_system_parameter(organization, parameter_key))
    balance, _ = LeaveBalance.objects.get_or_create(
        organization=organization,
        employee=employee,
        leave_type=leave_type,
        year=year,
        defaults={"allocated_days": allocated},
    )
    return balance


def decide_leave(*, leave, actor_membership, actor, approved, rejection_reason=""):
    with transaction.atomic():
        leave = LeaveRequest.objects.select_for_update().select_related("employee__reporting_manager").get(pk=leave.pk)
        if leave.status != LeaveRequest.Status.PENDING:
            raise ValidationError({"status": "Only pending leave requests can be approved or rejected."})
        if leave.employee.user_id == actor.id:
            raise ValidationError({"approval": "Employees cannot approve or reject their own leave."})
        is_manager = leave.employee.reporting_manager_id == getattr(actor_membership, "id", None)
        is_admin = is_organization_admin(actor_membership)
        if not (is_manager or is_admin or has_hr_admin_role(actor_membership)):
            raise PermissionDenied("Only the reporting manager or an HR Admin can decide this leave request.")
        if not approved and not rejection_reason.strip():
            raise ValidationError({"rejection_reason": "A rejection reason is required."})
        if approved:
            balance = ensure_leave_balance(
                organization=leave.organization,
                employee=leave.employee,
                leave_type=leave.leave_type,
                year=leave.from_date.year,
            )
            if balance.remaining_days < leave.days:
                raise ValidationError({"balance": "Insufficient leave balance."})
            balance.used_days += leave.days
            balance.save(update_fields=["used_days", "updated_at"])
        leave.status = LeaveRequest.Status.APPROVED if approved else LeaveRequest.Status.REJECTED
        leave.approved_by = actor
        leave.approved_at = timezone.now()
        leave.rejection_reason = "" if approved else rejection_reason.strip()
        leave.save(update_fields=["status", "approved_by", "approved_at", "rejection_reason", "updated_at"])
        log_activity(organization=leave.organization, employee=leave.employee,
                     action="leave_approved" if approved else "leave_rejected", actor=actor, module="leave",
                     details={"leave_id": leave.id})
        notify(
            leave.employee,
            "leave_decision",
            "Leave request approved" if approved else "Leave request rejected",
            "Your leave request has been approved." if approved else f"Your leave request was rejected: {leave.rejection_reason}",
            related=leave,
        )
        return leave


def has_hr_admin_role(membership):
    return bool(membership and membership.is_active and membership.organization_role and membership.organization_role.code == "hr-admin")


@transaction.atomic
def cancel_leave(*, leave, actor_membership, actor):
    leave = LeaveRequest.objects.select_for_update().select_related("employee").get(pk=leave.pk)
    if leave.employee_id != getattr(actor_membership, "id", None):
        raise PermissionDenied("Only the requesting employee can cancel this leave.")
    if leave.status not in {LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED}:
        raise ValidationError({"status": "Only pending or approved leave can be cancelled."})
    if leave.status == LeaveRequest.Status.APPROVED:
        balance = LeaveBalance.objects.select_for_update().get(
            employee=leave.employee, leave_type=canonical_leave_type(leave.leave_type), year=leave.from_date.year
        )
        balance.used_days = max(balance.used_days - leave.days, 0)
        balance.save(update_fields=["used_days", "updated_at"])
    leave.status = LeaveRequest.Status.CANCELLED
    leave.save(update_fields=["status", "updated_at"])
    log_activity(organization=leave.organization, employee=leave.employee, action="leave_cancelled", actor=actor, module="leave", details={"leave_id": leave.id})
    return leave
