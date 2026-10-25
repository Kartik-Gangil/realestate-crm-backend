from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
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
    "reject": "expenses.reject",
    "manage_categories": "expenses.manage_categories",
    "process_payment": "expenses.process_payment",
    "mark_paid": "expenses.mark_paid",
    "process_reimbursement": "expenses.process_reimbursement",
    "reports": "expenses.reports",
}


class ExpenseAlreadyPaid(Exception):
    """Raised when an authorized payment request targets an already-paid expense."""


def _has_any(user, organization, *permissions):
    return any(has_permission(user, organization, permission) for permission in permissions)


def can_create(user, organization):
    return _has_any(
        user,
        organization,
        EXPENSE_PERMISSIONS["edit_own"],
        EXPENSE_PERMISSIONS["submit"],
        "expenses.add",
        EXPENSE_PERMISSIONS["manage_categories"],
    )


def can_view(user, expense):
    if not expense or not expense.organization_id or expense.is_deleted:
        return False
    if _has_any(user, expense.organization, EXPENSE_PERMISSIONS["view_team"], "expenses.view"):
        return True
    return (
        expense.submitted_by_id == user.id
        and _has_any(user, expense.organization, EXPENSE_PERMISSIONS["view_own"], EXPENSE_PERMISSIONS["edit_own"], "expenses.edit")
    )


def can_edit(user, expense):
    return bool(
        expense
        and not expense.is_deleted
        and expense.status in {Expense.Status.DRAFT, Expense.Status.CHANGES_REQUESTED}
        and expense.submitted_by_id == user.id
        and _has_any(user, expense.organization, EXPENSE_PERMISSIONS["edit_own"], EXPENSE_PERMISSIONS["submit"], "expenses.edit", "expenses.add")
    )


def can_approve(user, expense):
    if not expense or expense.is_deleted or expense.status != Expense.Status.PENDING_APPROVAL:
        return False
    if not _has_any(user, expense.organization, EXPENSE_PERMISSIONS["approve"], "expenses.edit"):
        return False
    if is_platform_admin(user):
        return True
    membership = OrganizationMembership.objects.filter(
        organization=expense.organization, user=user, is_active=True
    ).select_related("organization_role").first()
    return membership_role_code(membership) in {
        OrganizationMembership.Role.ADMIN,
        OrganizationMembership.Role.MANAGER,
        "finance",
    }


def can_reject(user, expense):
    return bool(
        expense
        and not expense.is_deleted
        and expense.status == Expense.Status.PENDING_APPROVAL
        and _has_any(user, expense.organization, EXPENSE_PERMISSIONS["reject"])
    )


def expense_snapshot(expense):
    return {
        "expense_id": expense.expense_id,
        "status": expense.status,
        "payment_status": expense.payment_status,
        "amount": str(expense.amount),
        "category_id": expense.category_id,
        "submitted_by_id": expense.submitted_by_id,
        "is_advance": expense.is_advance,
    }


def log_activity(expense, action, actor=None, details=None):
    return ActivityLog.objects.create(
        expense=expense,
        action=action,
        actor=actor,
        details=details or {},
        snapshot=expense_snapshot(expense) if expense else {},
    )


@transaction.atomic
def submit_expense(expense, actor):
    if not can_edit(actor, expense):
        raise PermissionDenied("You can only submit your own editable expense.")
    if expense.status not in {Expense.Status.DRAFT, Expense.Status.CHANGES_REQUESTED}:
        raise ValidationError("Only draft or changes-requested expenses can be submitted.")
    expense.status = Expense.Status.PENDING_APPROVAL
    expense.rejection_reason = ""
    expense.save(update_fields=["status", "rejection_reason", "updated_at"])
    ApprovalStep.objects.get_or_create(
        expense=expense,
        step_name="Submitted",
        defaults={"status": ApprovalStep.Status.DONE, "actor": actor, "acted_at": timezone.now()},
    )
    manager_step, _ = ApprovalStep.objects.get_or_create(expense=expense, step_name="Manager Review")
    manager_step.status = ApprovalStep.Status.PENDING
    manager_step.actor = None
    manager_step.acted_at = None
    manager_step.comment = ""
    manager_step.save(update_fields=["status", "actor", "acted_at", "comment"])
    log_activity(expense, "Submitted", actor)
    return expense


def _current_approval_step(expense):
    return expense.approval_steps.filter(status=ApprovalStep.Status.PENDING).order_by("id").first()


def _ensure_manager_review_step(expense):
    """Repair legacy pending expenses that predate the manager-review step."""
    step = _current_approval_step(expense)
    if step is not None:
        return step
    manager_step, _ = ApprovalStep.objects.get_or_create(
        expense=expense,
        step_name="Manager Review",
        defaults={"status": ApprovalStep.Status.PENDING},
    )
    return manager_step if manager_step.status == ApprovalStep.Status.PENDING else None


@transaction.atomic
def approve_expense(expense, actor):
    if not can_approve(actor, expense):
        raise PermissionDenied("Only the assigned manager or an admin can approve this expense.")
    step = _ensure_manager_review_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    now = timezone.now()
    step.status = ApprovalStep.Status.DONE
    step.actor = actor
    step.acted_at = now
    step.save(update_fields=["status", "actor", "acted_at"])
    expense.status = Expense.Status.APPROVED
    expense.save(update_fields=["status", "updated_at"])
    ApprovalStep.objects.get_or_create(expense=expense, step_name="Finance")
    log_activity(expense, "Approved", actor)
    return expense


@transaction.atomic
def reject_expense(expense, actor, reason):
    if not can_reject(actor, expense):
        raise PermissionDenied("You do not have permission to reject this expense.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required when rejecting an expense."})
    step = _ensure_manager_review_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    step.status = ApprovalStep.Status.REJECTED
    step.actor = actor
    step.acted_at = timezone.now()
    step.comment = reason
    step.save(update_fields=["status", "actor", "acted_at", "comment"])
    expense.status = Expense.Status.REJECTED
    expense.rejection_reason = reason
    expense.save(update_fields=["status", "rejection_reason", "updated_at"])
    log_activity(expense, "Rejected", actor, {"reason": reason})
    return expense


@transaction.atomic
def request_expense_changes(expense, actor, comment):
    if not can_approve(actor, expense):
        raise PermissionDenied("Only the assigned manager or an admin can request changes.")
    comment = str(comment or "").strip()
    if not comment:
        raise ValidationError({"comment": "A comment is required when requesting changes."})
    step = _ensure_manager_review_step(expense)
    if not step or step.step_name != "Manager Review":
        raise ValidationError("This expense is not waiting for manager approval.")
    step.status = ApprovalStep.Status.REJECTED
    step.actor = actor
    step.acted_at = timezone.now()
    step.comment = comment
    step.save(update_fields=["status", "actor", "acted_at", "comment"])
    expense.status = Expense.Status.CHANGES_REQUESTED
    expense.rejection_reason = comment
    expense.save(update_fields=["status", "rejection_reason", "updated_at"])
    log_activity(expense, "Changes Requested", actor, {"comment": comment})
    return expense


def can_process_payment(user, expense):
    return bool(
        expense
        and not expense.is_deleted
        and expense.status == Expense.Status.APPROVED
        and expense.payment_status == Expense.PaymentStatus.UNPAID
        and _has_any(user, expense.organization, EXPENSE_PERMISSIONS["mark_paid"])
    )


def _organization_user(user_id, organization):
    user = get_user_model().objects.filter(pk=user_id).first()
    if not user:
        raise ValidationError({"paid_by": "Use a valid user ID."})
    if not is_platform_admin(user) and not OrganizationMembership.objects.filter(organization=organization, user=user, is_active=True).exists():
        raise ValidationError({"paid_by": "User must be an active member of this organization."})
    return user


@transaction.atomic
def mark_expense_paid(expense, actor, data):
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if not expense or expense.is_deleted or expense.status != Expense.Status.APPROVED or not _has_any(actor, expense.organization, EXPENSE_PERMISSIONS["mark_paid"]):
        raise PermissionDenied("Only Finance or an authorized admin can mark an expense paid.")
    if expense.payment_status == Expense.PaymentStatus.PAID:
        raise ExpenseAlreadyPaid
    if expense.payment_status != Expense.PaymentStatus.UNPAID:
        raise PermissionDenied("Only Finance or an authorized admin can mark an expense paid.")
    method = data.get("payment_method") or expense.payment_method
    if method not in Expense.PaymentMethod.values:
        raise ValidationError({"payment_method": "Use a valid payment method."})
    try:
        paid_amount = Decimal(str(data.get("paid_amount", expense.amount)))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError({"paid_amount": "Use a valid amount."}) from error
    if paid_amount <= 0 or paid_amount > expense.amount:
        raise ValidationError({"paid_amount": "Paid amount must be positive and cannot exceed the expense amount."})
    raw_paid_by = data.get("paid_by")
    paid_by_id = actor.id if raw_paid_by is None or not str(raw_paid_by).strip() else raw_paid_by
    paid_by = _organization_user(paid_by_id, expense.organization)
    payment = Payment.objects.create(
        expense=expense,
        payment_method=method,
        payment_date=data.get("payment_date") or timezone.localdate(),
        reference_no=str(data.get("reference_no", "")).strip(),
        paid_by=paid_by,
        paid_amount=paid_amount,
    )
    expense.payment_status = Expense.PaymentStatus.PAID
    expense.save(update_fields=["payment_status", "updated_at"])
    log_activity(expense, "Paid", actor, {"reference_no": payment.reference_no, "paid_amount": str(paid_amount)})
    return payment


def can_process_reimbursement(user, reimbursement):
    expense = reimbursement.expense
    return bool(
        expense
        and _has_any(user, expense.organization, EXPENSE_PERMISSIONS["process_reimbursement"], "expenses.add")
    )


@transaction.atomic
def adjust_reimbursement_advance(reimbursement, actor):
    if not can_process_reimbursement(actor, reimbursement):
        raise PermissionDenied("Only Finance or an authorized admin can adjust reimbursements.")
    advance = reimbursement.expense if reimbursement.expense and reimbursement.expense.is_advance else None
    reimbursement.advance_adjusted_amount = min(reimbursement.amount, advance.amount) if advance else Decimal("0")
    reimbursement.save(update_fields=["advance_adjusted_amount"])
    if advance:
        log_activity(advance, "Advance Adjusted", actor)
    return reimbursement


@transaction.atomic
def approve_reimbursement(reimbursement, actor):
    if not can_process_reimbursement(actor, reimbursement):
        raise PermissionDenied("Only Finance or an authorized admin can approve reimbursements.")
    if reimbursement.status != ReimbursementRequest.Status.PENDING:
        raise ValidationError("Only pending reimbursements can be approved.")
    reimbursement.status = ReimbursementRequest.Status.APPROVED
    reimbursement.resolved_on = timezone.now()
    reimbursement.save(update_fields=["status", "resolved_on"])
    if reimbursement.expense:
        log_activity(reimbursement.expense, "Reimbursement Approved", actor, {"transaction_reference": reimbursement.transaction_reference})
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
    if reimbursement.expense:
        log_activity(reimbursement.expense, "Reimbursement Rejected", actor)
    return reimbursement


@transaction.atomic
def cancel_expense(expense, actor):
    if expense.is_deleted or expense.status == Expense.Status.CANCELLED or expense.payment_status == Expense.PaymentStatus.PAID:
        raise ValidationError("This expense cannot be cancelled.")
    if expense.status == Expense.Status.APPROVED and not is_platform_admin(actor) and not has_permission(actor, expense.organization, "expenses.manage_categories"):
        raise PermissionDenied("Only an Admin can cancel an approved expense.")
    if expense.status != Expense.Status.APPROVED and expense.submitted_by_id != actor.id and not can_approve(actor, expense):
        raise PermissionDenied("You cannot cancel this expense.")
    expense.status = Expense.Status.CANCELLED
    expense.is_deleted = True
    expense.save(update_fields=["status", "is_deleted", "updated_at"])
    log_activity(expense, "Cancelled", actor)
    return expense
