from .models import Expense


def user_to_dict(user):
    if not user:
        return None
    return {"id": user.id, "email": user.email, "name": user.get_full_name() or user.get_username()}


def expense_to_dict(expense, detailed=False):
    data = {
        "id": expense.id,
        "expense_id": expense.expense_id,
        "organization": {"id": expense.organization_id, "slug": expense.organization.slug, "name": expense.organization.name},
        "date": expense.date.isoformat(),
        "category": {"id": expense.category_id, "name": expense.category.name, "is_active": expense.category.is_active},
        "amount": str(expense.amount),
        "description": expense.description,
        "payment_method": expense.payment_method,
        "paid_by": user_to_dict(expense.paid_by),
        "submitted_by": user_to_dict(expense.submitted_by),
        "receipt": expense.receipt.url if expense.receipt else None,
        "notes": expense.notes,
        "project_reference": expense.project_reference,
        "is_advance": expense.is_advance,
        "status": expense.status,
        "payment_status": expense.payment_status,
        "is_deleted": expense.is_deleted,
        "created_at": expense.created_at.isoformat(),
        "updated_at": expense.updated_at.isoformat(),
    }
    if detailed:
        data["approval_steps"] = [
            {"id": step.id, "step_name": step.step_name, "actor": user_to_dict(step.actor), "status": step.status, "acted_at": step.acted_at.isoformat() if step.acted_at else None, "comment": step.comment}
            for step in expense.approval_steps.all()
        ]
        data["activity"] = [
            {"id": item.id, "action": item.action, "actor": user_to_dict(item.actor), "action_date": item.action_date.isoformat(), "snapshot": item.snapshot}
            for item in expense.activity_logs.all()
        ]
    return data


def payment_to_dict(payment):
    return {
        "id": payment.id,
        "payment_status": payment.payment_status,
        "payment_method": payment.payment_method,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "reference_no": payment.reference_no,
        "paid_by": user_to_dict(payment.paid_by),
        "paid_amount": str(payment.paid_amount) if payment.paid_amount is not None else None,
        "expense": expense_to_dict(payment.expense),
    }


def reimbursement_to_dict(item):
    return {
        "id": item.id,
        "employee": user_to_dict(item.employee),
        "expense": expense_to_dict(item.expense) if item.expense_id else None,
        "amount": str(item.amount),
        "status": item.status,
        "requested_on": item.requested_on.isoformat(),
        "resolved_on": item.resolved_on.isoformat() if item.resolved_on else None,
        "advance_adjusted_amount": str(item.advance_adjusted_amount),
    }


def payment_queue_to_dict(expense):
    return {
        "expense": expense_to_dict(expense),
        "payment": payment_to_dict(expense.payment) if hasattr(expense, "payment") else None,
    }


def activity_log_to_dict(item):
    return {
        "id": item.id,
        "expense_id": item.expense.expense_id if item.expense_id else item.snapshot.get("expense_id"),
        "action": item.action,
        "actor": user_to_dict(item.actor),
        "action_date": item.action_date.isoformat(),
        "snapshot": item.snapshot,
    }


def category_to_dict(category):
    return {
        "id": category.id,
        "organization": {"id": category.organization_id, "slug": category.organization.slug, "name": category.organization.name},
        "name": category.name,
        "description": category.description,
        "is_active": category.is_active,
        "created_at": category.created_at.isoformat(),
        "updated_at": category.updated_at.isoformat(),
    }


EDITABLE_FIELDS = {"date", "category", "amount", "description", "payment_method", "paid_by", "receipt", "notes", "project_reference", "is_advance"}
