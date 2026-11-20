import os
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes, renderer_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from core.files import private_file_response
from core.audit_context import set_audit_action

from inventory.models import Project
from organizations.services import get_organization_access, get_project_context, has_permission, is_platform_admin
from organizations.models import OrganizationMembership

from .models import ActivityLog, ApprovalStep, Expense, ExpenseCategory, Payment, ReimbursementRequest
from .serializers import ExpenseCategorySerializer, ExpenseSerializer
from .services import (
    EXPENSE_PERMISSIONS,
    adjust_reimbursement_advance,
    approve_expense,
    approve_reimbursement,
    can_approve,
    can_create,
    can_edit,
    can_process_reimbursement,
    can_process_payment,
    can_reject,
    can_view,
    cancel_expense,
    ExpenseAlreadyPaid,
    ExpenseAlreadyReimbursed,
    log_activity,
    mark_expense_paid,
    reimburse_expense,
    reject_expense,
    reject_reimbursement,
    request_expense_changes,
    submit_expense,
)


class _ReportExportRenderer(BaseRenderer):
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        import json

        return json.dumps(data).encode(self.charset)


class ReportExportXlsxRenderer(_ReportExportRenderer):
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "xlsx"


class ReportExportPdfRenderer(_ReportExportRenderer):
    media_type = "application/pdf"
    format = "pdf"


def _organization_context(request):
    project_id = request.headers.get("X-Project-ID")
    if not project_id:
        memberships = OrganizationMembership.objects.filter(user=request.user, is_active=True).select_related("organization")
        if memberships.count() != 1:
            raise ValidationError({"project": "X-Project-ID is required to resolve the organization."})
        return memberships.first().organization, None
    try:
        int(project_id)
    except (TypeError, ValueError):
        raise ValidationError({"project": "X-Project-ID must be a valid project id."})
    project = Project.objects.select_related("organization").filter(pk=int(project_id)).first()
    if project is None:
        raise NotFound("Project not found.")
    access = get_organization_access(request.user, project.organization.slug)
    project = get_project_context(request, access)
    return access.organization, project


def _can_manage(request, organization, action, project=None):
    return can_create(request.user, organization, project=project) if action == "add" else has_permission(
        request.user, organization, f"expenses.{action}", project=project
    ) or has_permission(request.user, organization, "expenses.manage_categories", project=project)


def _envelope(data, success=True, request=None, error=None):
    return {
        "success": success,
        "data": data if success else None,
        "error": error,
        "meta": {
            "timestamp": timezone.now().isoformat(),
            "project_id": request.headers.get("X-Project-ID") if request else None,
        },
    }


def _parse_date(params, key):
    value = params.get(key)
    if not value:
        return None
    parsed = parse_date(value)
    if not parsed:
        raise ValidationError({key: "Use YYYY-MM-DD."})
    return parsed


def _paginate(request, items):
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "page and page_size must be integers."}) from error
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page_number = min(page_number, pages)
    start = (page_number - 1) * page_size
    return {
        "count": total,
        "page": page_number,
        "page_size": page_size,
        "num_pages": pages,
        "next": page_number + 1 if page_number < pages else None,
        "previous": page_number - 1 if page_number > 1 else None,
        "results": ExpenseSerializer(items[start:start + page_size], many=True, context={"request": request}).data,
    }


def _serialize_expense(expense, request, detailed=False):
    data = ExpenseSerializer(expense, context={"request": request}).data
    if not detailed:
        data.pop("approval_steps", None)
        data.pop("activity", None)
    return data


def _expense_queryset(organization, project, _access=None):
    # Expense visibility is governed by expenses.* permissions (view, view_own,
    # view_team), not by the cross-module employee data-scope selector.
    return Expense.objects.filter(
        organization=organization,
        project=project,
    ).select_related("category", "submitted_by", "paid_by").prefetch_related("approval_steps", "activity_logs")


def _category_in_context(category, organization, project):
    return (
        category.organization_id == organization.id
        and (category.project_id is None or (project and category.project_id == project.id))
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def category_list(request):
    organization, project = _organization_context(request)
    categories = ExpenseCategory.objects.filter(organization=organization)
    if project:
        categories = categories.filter(project=project)
    else:
        categories = categories.filter(project__isnull=True)
    if request.query_params.get("is_active") in {"true", "1"}:
        categories = categories.filter(is_active=True)
    if request.method == "GET":
        return Response(_envelope(ExpenseCategorySerializer(categories, many=True).data, request=request))
    if not _can_manage(request, organization, "add", project):
        raise PermissionDenied("You do not have permission to create expense categories.")
    serializer = ExpenseCategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    category = serializer.save(organization=organization, project=project)
    return Response(_envelope(ExpenseCategorySerializer(category).data, request=request), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def category_detail(request, category_id):
    organization, project = _organization_context(request)
    category = get_object_or_404(ExpenseCategory, pk=category_id, organization=organization)
    if project and category.project_id not in {None, project.id}:
        raise PermissionDenied("You do not have access to this project category.")
    if not _can_manage(request, organization, "edit", project):
        raise PermissionDenied("You do not have permission to edit expense categories.")
    serializer = ExpenseCategorySerializer(category, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    category = serializer.save()
    return Response(_envelope(ExpenseCategorySerializer(category).data, request=request))


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def expense_list(request):
    organization, project = _organization_context(request)
    if request.method == "GET":
        expenses = _expense_queryset(organization, project, get_organization_access(request.user, organization.slug)).filter(is_deleted=False)
        for field in ("status", "payment_status"):
            if request.query_params.get(field):
                expenses = expenses.filter(**{field: request.query_params[field]})
        if request.query_params.get("category"):
            expenses = expenses.filter(category_id=request.query_params["category"])
        start_date = _parse_date(request.query_params, "date_from")
        end_date = _parse_date(request.query_params, "date_to")
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"date_to": "date_to must be on or after date_from."})
        if start_date:
            expenses = expenses.filter(date__gte=start_date)
        if end_date:
            expenses = expenses.filter(date__lte=end_date)
        if search := request.query_params.get("search"):
            expenses = expenses.filter(Q(description__icontains=search) | Q(expense_id__icontains=search) | Q(project_reference__icontains=search))
        visible = [expense for expense in expenses if can_view(request.user, expense)]
        page = _paginate(request, visible)
        return Response(_envelope(page, request=request))
    if not _can_manage(request, organization, "add"):
        raise PermissionDenied("You do not have permission to log expenses.")
    if project is None:
        raise ValidationError({"project": "X-Project-ID is required for project expenses."})
    payload = request.data.copy()
    if "category" in payload and "category_id" not in payload:
        payload["category_id"] = request.data.get("category")
        payload.pop("category", None)
    if "paid_by" in payload and "paid_by_id" not in payload:
        if request.data.get("paid_by"):
            payload["paid_by_id"] = request.data.get("paid_by")
        payload.pop("paid_by", None)
    action = str(request.data.get("action", "draft")).lower().replace("_", "-")
    serializer = ExpenseSerializer(
        data=payload,
        context={"action": action, "organization": organization},
    )
    serializer.is_valid(raise_exception=True)
    category = serializer.validated_data["category"]
    if not _category_in_context(category, organization, project):
        raise ValidationError({"category": "Category must belong to the active organization and project."})
    paid_by = serializer.validated_data.get("paid_by")
    if paid_by and not OrganizationMembership.objects.filter(organization=organization, user=paid_by, is_active=True).exists():
        raise ValidationError({"paid_by": "Paid by must be an active member of the organization."})
    expense = serializer.save(organization=organization, project=project, submitted_by=request.user, status=Expense.Status.DRAFT)
    if action in {"submit", "submit-for-approval"}:
        submit_expense(expense, request.user)
    return Response(
        _envelope(ExpenseSerializer(expense, context={"request": request}).data, request=request),
        status=status.HTTP_201_CREATED,
    )


def _get_scoped_expense(request, expense_id):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    return get_object_or_404(_expense_queryset(organization, project, access), pk=expense_id), organization, project


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def expense_detail(request, expense_id):
    expense, organization, project = _get_scoped_expense(request, expense_id)
    if not can_view(request.user, expense) and not can_approve(request.user, expense) and not can_reject(request.user, expense):
        raise PermissionDenied("You do not have access to this expense.")
    if request.method == "GET":
        return Response(_envelope(_serialize_expense(expense, request, detailed=True), request=request))
    if expense.status == Expense.Status.APPROVED:
        return Response({"status": "Approved expenses are read-only."}, status=status.HTTP_400_BAD_REQUEST)
    if not can_edit(request.user, expense):
        raise PermissionDenied("You can only edit your own draft or changes-requested expense.")
    payload = request.data.copy()
    action = str(payload.get("action", "draft")).lower().replace("_", "-")
    payload.pop("action", None)
    if "category" in payload and "category_id" not in payload:
        payload["category_id"] = payload.pop("category")
    if "paid_by" in payload and "paid_by_id" not in payload:
        paid_by = payload.pop("paid_by")
        if paid_by:
            payload["paid_by_id"] = paid_by
    serializer = ExpenseSerializer(
        expense,
        data=payload,
        partial=True,
        context={"action": action, "organization": organization, "request": request},
    )
    serializer.is_valid(raise_exception=True)
    category = serializer.validated_data.get("category", expense.category)
    if not _category_in_context(category, organization, project):
        raise ValidationError({"category": "Category must belong to the active organization and project."})
    paid_by = serializer.validated_data.get("paid_by")
    if paid_by and not OrganizationMembership.objects.filter(organization=organization, user=paid_by, is_active=True).exists():
        raise ValidationError({"paid_by": "Paid by must be an active member of the organization."})
    expense = serializer.save()
    log_activity(expense, "Edited", request.user)
    if action in {"submit", "submit-for-approval"}:
        submit_expense(expense, request.user)
    return Response(_envelope(_serialize_expense(expense, request, detailed=True), request=request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_cancel(request, expense_id):
    expense, _, _ = _get_scoped_expense(request, expense_id)
    try:
        expense = cancel_expense(expense, request.user)
    except (ValidationError, DjangoValidationError) as error:
        return Response({"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_serialize_expense(expense, request), request=request))


def _approval_queue(request):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    queryset = _expense_queryset(organization, project, access).filter(status=Expense.Status.PENDING_APPROVAL, is_deleted=False)
    return [expense for expense in queryset if can_approve(request.user, expense) or can_reject(request.user, expense)]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_approval(request):
    items = _approval_queue(request)
    if not items:
        organization, project = _organization_context(request)
        if not has_permission(request.user, organization, EXPENSE_PERMISSIONS["approve"], project=project) and not has_permission(request.user, organization, EXPENSE_PERMISSIONS["reject"], project=project):
            raise PermissionDenied("You do not have permission to access the approval queue.")
    return Response(_envelope(_paginate(request, items), request=request))


def _run_approval_action(request, expense_id, action):
    expense, organization, project = _get_scoped_expense(request, expense_id)
    try:
        set_audit_action(request, action if action in {"approve", "reject"} else None)
        if action == "approve":
            expense = approve_expense(expense, request.user)
        elif action == "reject":
            expense = reject_expense(expense, request.user, request.data.get("reason") or request.data.get("comment"))
        else:
            expense = request_expense_changes(expense, request.user, request.data.get("comment"))
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    set_audit_action(request, None)
    return Response(_envelope(_serialize_expense(expense, request, detailed=True), request=request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_approve(request, expense_id):
    return _run_approval_action(request, expense_id, "approve")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_reject(request, expense_id):
    return _run_approval_action(request, expense_id, "reject")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_request_changes(request, expense_id):
    return _run_approval_action(request, expense_id, "request_changes")


def _payment_dict(payment):
    return {
        "id": payment.id,
        "payment_status": payment.payment_status,
        "payment_method": payment.payment_method,
        "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
        "reference_no": payment.reference_no,
        "paid_by": {"id": payment.paid_by_id, "name": payment.paid_by.get_username()} if payment.paid_by else None,
        "paid_amount": str(payment.paid_amount),
    }


def _payment_queue(request, paid):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    queryset = _expense_queryset(organization, project, access).filter(
        status=Expense.Status.APPROVED,
        payment_status=Expense.PaymentStatus.PAID if paid else Expense.PaymentStatus.UNPAID,
        is_deleted=False,
    )
    result = []
    for expense in queryset:
        if can_view(request.user, expense) or can_process_payment(request.user, expense):
            result.append({"expense": _serialize_expense(expense, request), "payment": _payment_dict(expense.payment) if hasattr(expense, "payment") else None})
    return result


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unpaid_payments(request):
    return Response(_envelope(_paginate_payment_items(request, _payment_queue(request, False)), request=request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paid_payments(request):
    return Response(_envelope(_paginate_payment_items(request, _payment_queue(request, True)), request=request))


def _paginate_payment_items(request, items):
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "page and page_size must be integers."}) from error
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page_number = min(page_number, pages)
    start = (page_number - 1) * page_size
    return {"count": total, "page": page_number, "page_size": page_size, "num_pages": pages, "results": items[start:start + page_size]}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_mark_paid(request, expense_id):
    expense, _, _ = _get_scoped_expense(request, expense_id)
    try:
        payment = mark_expense_paid(expense, request.user, request.data)
    except ExpenseAlreadyPaid:
        return Response(
            {"detail": "This expense has already been paid.", "code": "expense_already_paid"},
            status=status.HTTP_409_CONFLICT,
        )
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_payment_dict(payment), request=request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_reimburse(request, expense_id):
    expense, _, _ = _get_scoped_expense(request, expense_id)
    try:
        expense = reimburse_expense(expense, request.user, request.data.get("transaction_reference"))
    except ExpenseAlreadyReimbursed:
        return Response({"detail": "This expense has already been reimbursed.", "code": "expense_already_reimbursed"}, status=status.HTTP_409_CONFLICT)
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_serialize_expense(expense, request, detailed=True), request=request))


def _reimbursement_dict(item):
    return {
        "id": item.id,
        "employee": {"id": item.employee_id, "name": item.employee.get_username()} if item.employee else None,
        "expense": _serialize_expense(item.expense, None) if item.expense else None,
        "amount": str(item.amount),
        "status": item.status,
        "requested_on": item.requested_on.isoformat(),
        "resolved_on": item.resolved_on.isoformat() if item.resolved_on else None,
        "advance_adjusted_amount": str(item.advance_adjusted_amount),
        "transaction_reference": item.transaction_reference,
    }


def _reimbursement_items(request):
    organization, project = _organization_context(request)
    query = ReimbursementRequest.objects.filter(expense__organization=organization, expense__project=project).select_related("employee", "expense", "expense__category", "expense__submitted_by")
    if request.query_params.get("status"):
        query = query.filter(status=request.query_params["status"])
    return [item for item in query if item.expense and (can_view(request.user, item.expense) or can_process_reimbursement(request.user, item))]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reimbursement_list(request):
    items = _reimbursement_items(request)
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "page and page_size must be integers."}) from error
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page_number = min(page_number, pages)
    start = (page_number - 1) * page_size
    return Response(_envelope({"count": total, "page": page_number, "page_size": page_size, "num_pages": pages, "results": [_reimbursement_dict(item) for item in items[start:start + page_size]]}, request=request))


def _get_reimbursement(request, reimbursement_id):
    organization, project = _organization_context(request)
    return get_object_or_404(ReimbursementRequest.objects.select_related("expense", "employee"), pk=reimbursement_id, expense__organization=organization, expense__project=project)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_adjust_advance(request, reimbursement_id):
    item = _get_reimbursement(request, reimbursement_id)
    try:
        item = adjust_reimbursement_advance(item, request.user)
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_reimbursement_dict(item), request=request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_approve(request, reimbursement_id):
    item = _get_reimbursement(request, reimbursement_id)
    try:
        item = approve_reimbursement(item, request.user)
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_reimbursement_dict(item), request=request))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_reject(request, reimbursement_id):
    item = _get_reimbursement(request, reimbursement_id)
    try:
        item = reject_reimbursement(item, request.user)
    except (ValidationError, DjangoValidationError) as error:
        return Response(error.message_dict if hasattr(error, "message_dict") else {"detail": error.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_envelope(_reimbursement_dict(item), request=request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_history(request):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    scoped_expenses = _expense_queryset(organization, project, access)
    query = ActivityLog.objects.filter(expense__in=scoped_expenses).select_related("expense", "actor")
    if request.query_params.get("action"):
        query = query.filter(action=request.query_params["action"])
    items = [item for item in query if can_view(request.user, item.expense) or can_approve(request.user, item.expense)]
    rows = [{
        "id": item.id,
        "expense_id": item.expense.expense_id if item.expense else item.snapshot.get("expense_id"),
        "action": item.action,
        "actor": {"id": item.actor_id, "name": item.actor.get_username()} if item.actor else None,
        "action_date": item.action_date.isoformat(),
        "snapshot": item.snapshot,
        "details": item.details,
    } for item in items]
    return Response(_envelope(_paginate_history(request, rows), request=request))


def _paginate_history(request, items):
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "page and page_size must be integers."}) from error
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page_number = min(page_number, pages)
    start = (page_number - 1) * page_size
    return {"count": total, "page": page_number, "page_size": page_size, "num_pages": pages, "results": items[start:start + page_size]}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def deleted_expenses(request):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    query = _expense_queryset(organization, project, access).filter(is_deleted=True)
    items = [expense for expense in query if can_view(request.user, expense) or can_approve(request.user, expense)]
    return Response(_envelope(_paginate(request, items), request=request))


def _report_items(request):
    organization, project = _organization_context(request)
    access = get_organization_access(request.user, organization.slug)
    query = _expense_queryset(organization, project, access).filter(is_deleted=False)
    start_date = _parse_date(request.query_params, "start")
    end_date = _parse_date(request.query_params, "end")
    if start_date and end_date and start_date > end_date:
        raise ValidationError({"end": "end must be on or after start."})
    if start_date:
        query = query.filter(date__gte=start_date)
    if end_date:
        query = query.filter(date__lte=end_date)
    return [expense for expense in query if can_view(request.user, expense) or has_permission(request.user, organization, EXPENSE_PERMISSIONS["reports"], project=project)]


def _report_payload(request):
    expenses = _report_items(request)
    total = sum((expense.amount for expense in expenses), Decimal("0"))
    paid = sum((expense.amount for expense in expenses if expense.payment_status == Expense.PaymentStatus.PAID), Decimal("0"))
    pending = sum((expense.amount for expense in expenses if expense.status == Expense.Status.APPROVED and expense.payment_status == Expense.PaymentStatus.UNPAID), Decimal("0"))
    categories = {}
    dates = {}
    for expense in expenses:
        category = categories.setdefault(expense.category_id, {"category_id": expense.category_id, "category": expense.category.name, "amount": Decimal("0"), "count": 0})
        category["amount"] += expense.amount
        category["count"] += 1
        day = dates.setdefault(expense.date.isoformat(), {"date": expense.date.isoformat(), "amount": Decimal("0"), "count": 0})
        day["amount"] += expense.amount
        day["count"] += 1
    def normalize(row):
        row = dict(row)
        if "amount" in row:
            row["amount"] = str(row["amount"])
        return row
    return {
        "filters": {"start": request.query_params.get("start"), "end": request.query_params.get("end")},
        "totals": {"total_expenses": str(total), "paid": str(paid), "pending": str(pending), "reimbursements": str(sum((item.amount for expense in expenses for item in expense.reimbursement_requests.all()), Decimal("0")))},
        "counts": {"expenses": len(expenses), "paid": sum(expense.payment_status == Expense.PaymentStatus.PAID for expense in expenses), "pending": sum(expense.status == Expense.Status.APPROVED and expense.payment_status == Expense.PaymentStatus.UNPAID for expense in expenses), "reimbursements": sum(expense.reimbursement_requests.count() for expense in expenses)},
        "category_breakdown": [normalize(item) for item in categories.values()],
        "expenses_over_time": [normalize(item) for item in dates.values()],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_summary(request):
    return Response(_envelope(_report_payload(request), request=request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([ReportExportXlsxRenderer, ReportExportPdfRenderer])
def report_export(request):
    organization, project = _organization_context(request)
    if not is_platform_admin(request.user) and not has_permission(request.user, organization, "reports.export", project=project):
        raise PermissionDenied("Export permission is required.")
    report_format = request.query_params.get("format", "xlsx").lower()
    if report_format not in {"xlsx", "pdf"}:
        return Response({"format": "Use xlsx or pdf."}, status=status.HTTP_400_BAD_REQUEST)
    report = _report_payload(request)
    if report_format == "xlsx":
        from openpyxl import Workbook
        from io import BytesIO
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Expense Summary"
        sheet.append(["Metric", "Amount"])
        sheet.append(["Total Expenses", report["totals"]["total_expenses"]])
        sheet.append(["Paid", report["totals"]["paid"]])
        sheet.append(["Pending", report["totals"]["pending"]])
        sheet.append(["Reimbursements", report["totals"]["reimbursements"]])
        categories = workbook.create_sheet("Category Breakdown")
        categories.append(["Category", "Amount", "Count"])
        for item in report["category_breakdown"]:
            categories.append([item["category"], item["amount"], item["count"]])
        timeline = workbook.create_sheet("Expenses Over Time")
        timeline.append(["Date", "Amount", "Count"])
        for item in report["expenses_over_time"]:
            timeline.append([item["date"], item["amount"], item["count"]])
        output = BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="expense-report.xlsx"'
        return response
    from io import BytesIO
    from reportlab.pdfgen import canvas
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.setTitle("Expense report")
    pdf.drawString(50, 800, "Expense Report")
    y = 770
    for label, value in report["totals"].items():
        pdf.drawString(50, y, f"{label}: {value}")
        y -= 20
    pdf.save()
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="expense-report.pdf"'
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_receipt(request, expense_id):
    expense, organization, project = _get_scoped_expense(request, expense_id)
    can_review_pending_expense = can_approve(request.user, expense) or can_reject(request.user, expense)
    is_recorded_reviewer = expense.approval_steps.filter(
        actor_id=request.user.id,
        status__in=(ApprovalStep.Status.DONE, ApprovalStep.Status.REJECTED),
    ).exists()
    if not has_permission(request.user, organization, "expenses.export", project=project) and not (
        can_review_pending_expense or is_recorded_reviewer
    ):
        raise PermissionDenied("You do not have access to this expense receipt.")
    return private_file_response(expense.receipt, filename=os.path.basename(expense.receipt.name or "") or "receipt")
