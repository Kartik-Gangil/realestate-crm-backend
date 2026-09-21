from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from organizations.models import OrganizationMembership
from organizations.services import has_permission, is_platform_admin, membership_role_code

from .models import ActivityLog, ApprovalStep, Expense, Payment, ReimbursementRequest


EXPENSE_PERMISSIONS = {
    "view_own": "expenses.view_own",
    "edit_own": "expenses.edit_own",
    "submit": "expenses.submit",
    "view_team": "expenses.view_team",
    "approve": "expenses.approve",
    "manage_categories": "expenses.manage_categories",
    "process_payment": "expenses.process_payment",
    "process_reimbursement": "expenses.process_reimbursement",
    "reports": "expenses.reports",
}


def can_view(user, expense):
    if not expense or not expense.organization_id:
        return False
    if has_permission(user, expense.organization, EXPENSE_PERMISSIONS["view_team"]):
        return True
    return (
        expense.paid_by_id == user.id or expense.submitted_by_id == user.id
    ) and has_permission(user, expense.organization, EXPENSE_PERMISSIONS["view_own"])


def can_edit(user, expense):
    return bool(expense and not expense.is_deleted and expense.status in {Expense.Status.DRAFT, Expense.Status.CHANGES_REQUESTED} and expense.submitted_by_id == user.id and has_permission(user, expense.organization, EXPENSE_PERMISSIONS["edit_own"]))


def can_approve(user, expense):
    if not expense or expense.is_deleted or expense.status != Expense.Status.PENDING_APPROVAL:
        return False
    if not has_permission(user, expense.organization, EXPENSE_PERMISSIONS["approve"]):
        return False
    if is_platform_admin(user):
        return True
    actor_membership = OrganizationMembership.objects.filter(organization=expense.organization, user=user, is_active=True).select_related("organization_role").first()
    submitter_membership = OrganizationMembership.objects.filter(organization=expense.organization, user_id=expense.submitted_by_id, is_active=True).first()
    role_code = membership_role_code(actor_membership)
    if role_code in {OrganizationMembership.Role.ADMIN, "finance"}:
        return True
    if role_code == OrganizationMembership.Role.MANAGER:
        return not submitter_membership or not submitter_membership.reporting_manager_id or submitter_membership.reporting_manager_id == actor_membership.id
    return False


def expense_snapshot(expense):
    return {"expense_id": expense.expense_id, "status": expense.status, "payment_status": expense.payment_status, "amount": str(expense.amount), "category_id": expense.category_id, "submitted_by_id": expense.submitted_by_id, "is_advance": expense.is_advance}


def log_activity(expense, action, actor=None):
    return ActivityLog.objects.create(expense=expense, action=action, actor=actor, snapshot=expense_snapshot(expense))


@transaction.atomic
def submit_expense(expense, actor):
    if not can_edit(actor, expense):
        raise PermissionDenied("You can only submit your own editable expense.")
    threshold = Decimal(str(getattr(settings, "EXPENSE_RECEIPT_THRESHOLD", "5000")))
    if expense.amount > threshold and not expense.receipt:
        raise ValidationError({"receipt": f"A receipt is mandatory for expenses above {threshold}."})
    expense.status = Expense.Status.PENDING_APPROVAL
    expense.save(update_fields=["status", "updated_at"])
    ApprovalStep.objects.get_or_create(expense=expense, step_name="Submitted", defaults={"status": ApprovalStep.Status.DONE, "actor": actor, "acted_at": timezone.now()})
    manager_step, _ = ApprovalStep.objects.get_or_create(expense=expense, step_name="Manager Review")
    if manager_step.status != ApprovalStep.Status.PENDING:
        manager_step.status = ApprovalStep.Status.PENDING
        manager_step.actor = None
        manager_step.acted_at = None
        manager_step.comment = ""
        manager_step.save(update_fields=["status", "actor", "acted_at", "comment"])
    log_activity(expense, "Submitted", actor)
    return expense


def _current_approval_step(expense):
    return expense.approval_steps.filter(status=ApprovalStep.Status.PENDING).order_by("id").first()


@transaction.atomic
def approve_expense(expense, actor):
    if not can_approve(actor, expense):
        raise PermissionDenied("Only the assigned manager, Finance, or an admin can approve this expense.")
    step = _current_approval_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    now = timezone.now()
    step.status = ApprovalStep.Status.DONE
    step.actor = actor
    step.acted_at = now
    step.comment = ""
    step.save(update_fields=["status", "actor", "acted_at", "comment"])
    expense.status = Expense.Status.APPROVED
    expense.save(update_fields=["status", "updated_at"])
    ApprovalStep.objects.get_or_create(expense=expense, step_name="Finance")
    log_activity(expense, "Approved", actor)
    return expense


@transaction.atomic
def reject_expense(expense, actor, comment):
    if not can_approve(actor, expense):
        raise PermissionDenied("Only the assigned manager, Finance, or an admin can reject this expense.")
    if not comment or not comment.strip():
        raise ValidationError({"comment": "A comment is required when rejecting an expense."})
    step = _current_approval_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    step.status = ApprovalStep.Status.REJECTED
    step.actor = actor
    step.acted_at = timezone.now()
    step.comment = comment.strip()
    step.save(update_fields=["status", "actor", "acted_at", "comment"])
    expense.status = Expense.Status.REJECTED
    expense.save(update_fields=["status", "updated_at"])
    log_activity(expense, "Rejected", actor)
    return expense


@transaction.atomic
def request_expense_changes(expense, actor, comment=""):
    if not can_approve(actor, expense):
        raise PermissionDenied("Only the assigned manager, Finance, or an admin can request changes.")
    step = _current_approval_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    step.status = ApprovalStep.Status.REJECTED
    step.actor = actor
    step.acted_at = timezone.now()
    step.comment = comment.strip()
    step.save(update_fields=["status", "actor", "acted_at", "comment"])
    expense.status = Expense.Status.CHANGES_REQUESTED
    expense.save(update_fields=["status", "updated_at"])
    log_activity(expense, "Changes Requested", actor)
    return expense


def can_process_payment(user, expense):
    return bool(expense and not expense.is_deleted and expense.status == Expense.Status.APPROVED and expense.payment_status == Expense.PaymentStatus.UNPAID and has_permission(user, expense.organization, EXPENSE_PERMISSIONS["process_payment"]))


def _organization_user(user_id, organization):
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    if not user:
        raise ValidationError({"paid_by": "Use a valid user ID."})
    if not is_platform_admin(user) and not OrganizationMembership.objects.filter(organization=organization, user=user, is_active=True).exists():
        raise ValidationError({"paid_by": "User must be an active member of this organization."})
    return user


@transaction.atomic
def mark_expense_paid(expense, actor, data):
    if not can_process_payment(actor, expense):
        raise PermissionDenied("Only Finance or an authorized admin can mark approved expenses as paid.")
    method = data.get("payment_method")
    if method not in Expense.PaymentMethod.values:
        raise ValidationError({"payment_method": "Use a valid payment method."})
    payment_date = data.get("payment_date") or timezone.localdate()
    if isinstance(payment_date, str):
        from django.utils.dateparse import parse_date
        payment_date = parse_date(payment_date)
    if payment_date is None:
        raise ValidationError({"payment_date": "Use YYYY-MM-DD."})
    try:
        paid_amount = Decimal(str(data.get("paid_amount", expense.amount)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"paid_amount": "Use a valid amount."}) from exc
    if paid_amount <= 0 or paid_amount > expense.amount:
        raise ValidationError({"paid_amount": "Paid amount must be positive and cannot exceed the expense amount."})
    paid_by = _organization_user(data.get("paid_by", actor.id), expense.organization)
    payment = Payment.objects.create(expense=expense, payment_method=method, payment_status=Expense.PaymentStatus.PAID, payment_date=payment_date, reference_no=str(data.get("reference_no", "")).strip(), paid_by=paid_by, paid_amount=paid_amount)
    expense.payment_status = Expense.PaymentStatus.PAID
    expense._allow_mutation = True
    expense.save(update_fields=["payment_status", "updated_at"])
    log_activity(expense, "Paid", actor)
    return payment


def can_process_reimbursement(user, reimbursement):
    expense = reimbursement.expense
    if expense:
        return has_permission(user, expense.organization, EXPENSE_PERMISSIONS["process_reimbursement"])
    organizations = OrganizationMembership.objects.filter(user=user, is_active=True).values_list("organization", flat=True)
    return any(has_permission(user, organization, EXPENSE_PERMISSIONS["process_reimbursement"]) for organization in organizations)


def _reimbursement_expense(reimbursement):
    expense = reimbursement.expense
    if expense and expense.is_advance:
        return expense
    return None


@transaction.atomic
def adjust_reimbursement_advance(reimbursement, actor):
    if not can_process_reimbursement(actor, reimbursement):
        raise PermissionDenied("Only Finance or an authorized admin can adjust reimbursements.")
    advance = _reimbursement_expense(reimbursement)
    reimbursement.advance_adjusted_amount = min(reimbursement.amount, advance.amount) if advance else Decimal("0")
    reimbursement.save(update_fields=["advance_adjusted_amount"])
    log_activity(advance, "Advance Adjusted", actor) if advance else ActivityLog.objects.create(action="Advance Adjusted", actor=actor, snapshot={"reimbursement_id": reimbursement.id, "amount": str(reimbursement.amount)})
    return reimbursement


@transaction.atomic
def approve_reimbursement(reimbursement, actor):
    if not can_process_reimbursement(actor, reimbursement):
        raise PermissionDenied("Only Finance or an authorized admin can approve reimbursements.")
    if reimbursement.status != ReimbursementRequest.Status.PENDING:
        raise ValidationError("Only pending reimbursements can be approved.")
    advance = _reimbursement_expense(reimbursement)
    required_adjustment = min(reimbursement.amount, advance.amount) if advance else Decimal("0")
    if reimbursement.advance_adjusted_amount < required_adjustment:
        raise ValidationError({"advance_adjusted_amount": "Adjust linked advance expenses before approval."})
    reimbursement.status = ReimbursementRequest.Status.APPROVED
    reimbursement.resolved_on = timezone.now()
    reimbursement.save(update_fields=["status", "resolved_on"])
    log_activity(advance, "Reimbursement Approved", actor) if advance else ActivityLog.objects.create(action="Reimbursement Approved", actor=actor, snapshot={"reimbursement_id": reimbursement.id, "amount": str(reimbursement.amount)})
    return reimbursement


@transaction.atomic
def reject_reimbursement(reimbursement, actor):
    if not can_process_reimbursement(actor, reimbursement):
        raise PermissionDenied("Only Finance or an authorized admin can reject reimbursements.")
    if reimbursement.status != ReimbursementRequest.Status.PENDING:
        raise ValidationError("Only pending reimbursements can be rejected.")
    reimbursement.status = ReimbursementRequest.Status.REJECTED
    reimbursement.resolved_on = timezone.now()
    reimbursement.save(update_fields=["status", "resolved_on"])
    advance = _reimbursement_expense(reimbursement)
    log_activity(advance, "Reimbursement Rejected", actor) if advance else ActivityLog.objects.create(action="Reimbursement Rejected", actor=actor, snapshot={"reimbursement_id": reimbursement.id})
    return reimbursement


@transaction.atomic
def cancel_expense(expense, actor):
    if expense.is_deleted or expense.status == Expense.Status.CANCELLED or expense.payment_status == Expense.PaymentStatus.PAID:
        raise ValidationError("This expense cannot be cancelled.")
    actor_membership = OrganizationMembership.objects.filter(organization=expense.organization, user=actor, is_active=True).first()
    if expense.status == Expense.Status.APPROVED and not (is_platform_admin(actor) or membership_role_code(actor_membership) == OrganizationMembership.Role.ADMIN):
        raise PermissionDenied("Only an organization admin can cancel an approved expense.")
    if expense.status != Expense.Status.APPROVED and expense.submitted_by_id != actor.id and not has_permission(actor, expense.organization, EXPENSE_PERMISSIONS["approve"]):
        raise PermissionDenied("You cannot cancel this expense.")
    expense.status = Expense.Status.CANCELLED
    expense.is_deleted = True
    expense._allow_mutation = True
    expense.save(update_fields=["status", "is_deleted", "updated_at"])
    log_activity(expense, "Cancelled", actor)
    return expense
