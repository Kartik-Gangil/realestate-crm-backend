from datetime import date

from django.core.exceptions import ValidationError
from collections import defaultdict
from decimal import Decimal

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from organizations.models import Organization, OrganizationMembership
from organizations.services import get_organization_access, has_permission, is_platform_admin

from .models import ActivityLog, Expense, ExpenseCategory, Payment, ReimbursementRequest
from .serializers import (EDITABLE_FIELDS, activity_log_to_dict, category_to_dict, expense_to_dict,
                          payment_queue_to_dict, payment_to_dict, reimbursement_to_dict)
from .services import (EXPENSE_PERMISSIONS, approve_expense, can_approve, can_edit, can_view,
                       approve_reimbursement, cancel_expense, can_process_reimbursement,
                       mark_expense_paid, log_activity, reject_expense, reject_reimbursement,
                       request_expense_changes, submit_expense, adjust_reimbursement_advance)


def _accessible_organizations(user):
    if is_platform_admin(user):
        return Organization.objects.filter(is_active=True)
    return Organization.objects.filter(memberships__user=user, memberships__is_active=True, is_active=True).distinct()


def _parse_date_param(params, key):
    value = params.get(key)
    if not value:
        return None
    parsed = parse_date(value)
    if not parsed:
        raise ValidationError({key: "Use YYYY-MM-DD."})
    return parsed


def _report_expenses(request):
    start_date = _parse_date_param(request.query_params, "start")
    end_date = _parse_date_param(request.query_params, "end")
    if start_date and end_date and start_date > end_date:
        raise ValidationError({"end": "end must be on or after start."})
    queryset = Expense.objects.filter(
        organization__in=_accessible_organizations(request.user),
        is_deleted=False,
    ).select_related("organization", "category", "paid_by", "submitted_by")
    if start_date:
        queryset = queryset.filter(date__gte=start_date)
    if end_date:
        queryset = queryset.filter(date__lte=end_date)
    return [expense for expense in queryset if can_view(request.user, expense)], start_date, end_date


def _report_reimbursements(request, expenses):
    expense_ids = [expense.id for expense in expenses]
    queryset = ReimbursementRequest.objects.filter(expense_id__in=expense_ids).select_related("expense", "employee")
    return [item for item in queryset if _reimbursement_visible(request.user, item)]


def _paginate(request, queryset):
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "page and page_size must be integers."}) from exc
    page = Paginator(queryset, page_size).get_page(page_number)
    return {"count": page.paginator.count, "page": page.number, "page_size": page_size, "num_pages": page.paginator.num_pages, "next": page.next_page_number() if page.has_next() else None, "previous": page.previous_page_number() if page.has_previous() else None, "results": [expense_to_dict(item) for item in page.object_list]}


def _paginate_items(request, items, serializer):
    try:
        page_size = min(max(int(request.query_params.get("page_size", 25)), 1), 100)
        page_number = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "page and page_size must be integers."}) from exc
    page = Paginator(items, page_size).get_page(page_number)
    return {"count": page.paginator.count, "page": page.number, "page_size": page_size, "num_pages": page.paginator.num_pages, "next": page.next_page_number() if page.has_next() else None, "previous": page.previous_page_number() if page.has_previous() else None, "results": [serializer(item) for item in page.object_list]}


def _resolve_organization(request, payload=None):
    payload = payload or request.data
    value = payload.get("organization") or request.query_params.get("organization")
    organizations = _accessible_organizations(request.user)
    if value:
        organization = organizations.filter(Q(slug=value) | Q(pk=value if str(value).isdigit() else -1)).first()
        if not organization:
            raise PermissionDenied("You do not have access to this organization.")
        return organization
    if organizations.count() == 1:
        return organizations.first()
    raise ValidationError({"organization": "This field is required when the user belongs to multiple organizations."})


def _parse_payload_value(data, name, default=None):
    return data.get(name, default)


def _apply_payload(expense, data, *, creating=False):
    errors = {}
    category_id = _parse_payload_value(data, "category")
    if category_id is not None:
        try:
            expense.category = ExpenseCategory.objects.get(pk=category_id, organization=expense.organization, is_active=True)
        except (ExpenseCategory.DoesNotExist, TypeError, ValueError):
            errors["category"] = "Use an active category in this organization."
    elif creating:
        errors["category"] = "This field is required."
    for field in ("date", "amount", "description", "payment_method", "notes", "project_reference", "is_advance"):
        if field not in data:
            continue
        value = data[field]
        if field == "date":
            value = parse_date(str(value)) if value else None
            if value is None:
                errors[field] = "Use YYYY-MM-DD."
        elif field == "is_advance":
            value = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes"}
        setattr(expense, field, value)
    if "paid_by" in data:
        try:
            expense.paid_by_id = int(data["paid_by"])
        except (TypeError, ValueError):
            errors["paid_by"] = "Use a valid user ID."
    elif creating:
        expense.paid_by = expense.submitted_by
    if "receipt" in data:
        expense.receipt = data["receipt"]
    if creating and not expense.description:
        errors["description"] = "This field is required."
    if creating and not expense.payment_method:
        errors["payment_method"] = "This field is required."
    if errors:
        raise ValidationError(errors)
    expense.full_clean()


def _action(request):
    return str(request.data.get("action") or request.query_params.get("action") or "draft").lower().replace("_", "-")


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def expense_list(request):
    if request.method == "GET":
        queryset = Expense.objects.filter(organization__in=_accessible_organizations(request.user), is_deleted=False).select_related("organization", "category", "paid_by", "submitted_by")
        for field in ("status", "payment_status"):
            if request.query_params.get(field):
                queryset = queryset.filter(**{field: request.query_params[field]})
        if request.query_params.get("category"):
            queryset = queryset.filter(category_id=request.query_params["category"])
        start_date = _parse_date_param(request.query_params, "date_from")
        end_date = _parse_date_param(request.query_params, "date_to")
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"date_to": "date_to must be on or after date_from."})
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if search := request.query_params.get("search"):
            queryset = queryset.filter(Q(description__icontains=search) | Q(id__icontains=search.removeprefix("EXP")))
        queryset = [expense for expense in queryset if can_view(request.user, expense)]
        return Response(_paginate(request, queryset))

    try:
        organization = _resolve_organization(request)
        submitted_by = request.user
        expense = Expense(organization=organization, submitted_by=submitted_by, paid_by=submitted_by)
        _apply_payload(expense, request.data, creating=True)
        with transaction.atomic():
            expense.save()
            log_activity(expense, "Created", request.user)
            if _action(request) in {"submit", "submit-for-approval"}:
                submit_expense(expense, request.user)
        return Response(expense_to_dict(expense, detailed=True), status=status.HTTP_201_CREATED)
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_approval(request):
    organizations = _accessible_organizations(request.user)
    if not is_platform_admin(request.user) and not any(has_permission(request.user, organization, EXPENSE_PERMISSIONS["approve"]) for organization in organizations):
        raise PermissionDenied("Only managers, Finance, or admins can access the approval queue.")
    queryset = Expense.objects.filter(
        organization__in=organizations,
        status=Expense.Status.PENDING_APPROVAL,
        is_deleted=False,
    ).select_related("organization", "category", "paid_by", "submitted_by").prefetch_related("approval_steps")
    results = []
    for expense in queryset:
        if can_approve(request.user, expense) and expense.approval_steps.filter(step_name="Manager Review", status="pending").exists():
            results.append(expense)
    return Response(_paginate(request, results))


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def expense_detail(request, expense_id):
    expense = get_object_or_404(Expense.objects.select_related("organization", "category", "paid_by", "submitted_by").prefetch_related("approval_steps__actor", "activity_logs__actor"), pk=expense_id)
    if not can_view(request.user, expense):
        raise PermissionDenied("You do not have access to this expense.")
    if request.method == "GET":
        return Response(expense_to_dict(expense, detailed=True))
    if expense.status == Expense.Status.APPROVED:
        return Response({"status": "Approved expenses are read-only."}, status=status.HTTP_400_BAD_REQUEST)
    if not can_edit(request.user, expense):
        raise PermissionDenied("You can only edit your own draft or changes-requested expense.")
    unknown = set(request.data) - EDITABLE_FIELDS
    if unknown:
        return Response({field: "This field cannot be edited." for field in unknown}, status=status.HTTP_400_BAD_REQUEST)
    try:
        _apply_payload(expense, request.data)
        expense.save()
        log_activity(expense, "Edited", request.user)
        return Response(expense_to_dict(expense, detailed=True))
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_cancel(request, expense_id):
    expense = get_object_or_404(Expense.objects.select_related("organization", "category", "paid_by", "submitted_by"), pk=expense_id)
    if expense.status == Expense.Status.APPROVED:
        return Response({"status": "Approved expenses cannot be cancelled until the cancellation policy is confirmed."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        expense = cancel_expense(expense, request.user)
        return Response(expense_to_dict(expense))
    except (ValidationError, PermissionDenied) as exc:
        if isinstance(exc, PermissionDenied):
            raise
        return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_history(request):
    organizations = _accessible_organizations(request.user)
    queryset = ActivityLog.objects.filter(expense__organization__in=organizations).select_related("expense", "expense__organization", "actor").order_by("-action_date", "-id")
    if request.query_params.get("action"):
        queryset = queryset.filter(action=request.query_params["action"])
    visible = [item for item in queryset if item.expense and can_view(request.user, item.expense)]
    return Response(_paginate_items(request, visible, activity_log_to_dict))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def deleted_expenses(request):
    queryset = Expense.objects.filter(organization__in=_accessible_organizations(request.user), is_deleted=True).select_related("organization", "category", "paid_by", "submitted_by")
    visible = [expense for expense in queryset if can_view(request.user, expense)]
    return Response(_paginate(request, visible))


def _can_manage_categories(user, organization):
    return is_platform_admin(user) or has_permission(user, organization, EXPENSE_PERMISSIONS["manage_categories"])


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def category_list(request):
    organizations = [organization for organization in _accessible_organizations(request.user) if _can_manage_categories(request.user, organization)]
    if not organizations:
        raise PermissionDenied("Only Finance or admins can manage expense categories.")
    if request.method == "GET":
        categories = ExpenseCategory.objects.filter(organization__in=organizations).select_related("organization")
        if request.query_params.get("organization"):
            categories = categories.filter(organization__slug=request.query_params["organization"])
        if request.query_params.get("is_active") in {"true", "false"}:
            categories = categories.filter(is_active=request.query_params["is_active"] == "true")
        return Response([category_to_dict(category) for category in categories])
    try:
        organization = _resolve_organization(request)
        if not _can_manage_categories(request.user, organization):
            raise PermissionDenied("Only Finance or admins can manage categories in this organization.")
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"name": "This field is required."}, status=status.HTTP_400_BAD_REQUEST)
        category = ExpenseCategory(organization=organization, name=name, description=str(request.data.get("description", "")).strip(), is_active=request.data.get("is_active", True) not in {False, "false", "0"})
        category.full_clean()
        category.save()
        return Response(category_to_dict(category), status=status.HTTP_201_CREATED)
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def category_detail(request, category_id):
    category = get_object_or_404(ExpenseCategory.objects.select_related("organization"), pk=category_id)
    if not _can_manage_categories(request.user, category.organization):
        raise PermissionDenied("Only Finance or admins can manage expense categories.")
    allowed = {"name", "description", "is_active"}
    unknown = set(request.data) - allowed
    if unknown:
        return Response({field: "This field cannot be edited." for field in unknown}, status=status.HTTP_400_BAD_REQUEST)
    if "name" in request.data:
        category.name = str(request.data["name"]).strip()
    if "description" in request.data:
        category.description = str(request.data["description"])
    if "is_active" in request.data:
        category.is_active = request.data["is_active"] if isinstance(request.data["is_active"], bool) else str(request.data["is_active"]).lower() in {"true", "1", "yes"}
    try:
        category.full_clean()
        category.save()
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
    return Response(category_to_dict(category))


def _report_payload(request):
    expenses, start_date, end_date = _report_expenses(request)
    reimbursements = _report_reimbursements(request, expenses)
    total = sum((expense.amount for expense in expenses), Decimal("0"))
    paid = sum((expense.amount for expense in expenses if expense.payment_status == Expense.PaymentStatus.PAID), Decimal("0"))
    pending = sum((expense.amount for expense in expenses if expense.payment_status == Expense.PaymentStatus.UNPAID and expense.status == Expense.Status.APPROVED), Decimal("0"))
    reimbursement_total = sum((item.amount for item in reimbursements), Decimal("0"))
    category_totals = defaultdict(lambda: {"category_id": None, "category": "", "amount": Decimal("0"), "count": 0})
    time_totals = defaultdict(lambda: {"amount": Decimal("0"), "count": 0})
    for expense in expenses:
        category = category_totals[expense.category_id]
        category["category_id"] = expense.category_id
        category["category"] = expense.category.name
        category["amount"] += expense.amount
        category["count"] += 1
        time_totals[expense.date]["amount"] += expense.amount
        time_totals[expense.date]["count"] += 1
    return {
        "filters": {"start": start_date.isoformat() if start_date else None, "end": end_date.isoformat() if end_date else None},
        "totals": {"total_expenses": str(total), "paid": str(paid), "pending": str(pending), "reimbursements": str(reimbursement_total)},
        "counts": {"expenses": len(expenses), "paid": sum(expense.payment_status == Expense.PaymentStatus.PAID for expense in expenses), "pending": sum(expense.payment_status == Expense.PaymentStatus.UNPAID and expense.status == Expense.Status.APPROVED for expense in expenses), "reimbursements": len(reimbursements)},
        "category_breakdown": [{**item, "amount": str(item["amount"])} for item in sorted(category_totals.values(), key=lambda item: item["category"])],
        "expenses_over_time": [{"date": day.isoformat(), "amount": str(values["amount"]), "count": values["count"]} for day, values in sorted(time_totals.items())],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_summary(request):
    try:
        return Response(_report_payload(request))
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_export(request):
    try:
        payload = _report_payload(request)
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
    export_format = request.query_params.get("format", "xlsx").lower()
    if export_format == "xlsx":
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Expense Summary"
        sheet.append(["Metric", "Amount", "Count"])
        for key, label in (("total_expenses", "Total Expenses"), ("paid", "Paid"), ("pending", "Pending"), ("reimbursements", "Reimbursements")):
            sheet.append([label, payload["totals"][key], payload["counts"].get(key, payload["counts"].get("expenses", 0))])
        categories = workbook.create_sheet("Category Breakdown")
        categories.append(["Category", "Amount", "Count"])
        for item in payload["category_breakdown"]:
            categories.append([item["category"], item["amount"], item["count"]])
        timeline = workbook.create_sheet("Expenses Over Time")
        timeline.append(["Date", "Amount", "Count"])
        for item in payload["expenses_over_time"]:
            timeline.append([item["date"], item["amount"], item["count"]])
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="expense-report.xlsx"'
        workbook.save(response)
        return response
    if export_format == "pdf":
        from xhtml2pdf import pisa
        html = render_to_string("expenses/report.html", {"report": payload})
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="expense-report.pdf"'
        result = pisa.CreatePDF(html, dest=response)
        if result.err:
            return Response({"detail": "Could not generate the PDF report."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return response
    return Response({"format": "Use xlsx or pdf."}, status=status.HTTP_400_BAD_REQUEST)


def _workflow_response(request, expense_id, operation):
    expense = get_object_or_404(Expense.objects.select_related("organization", "category", "paid_by", "submitted_by"), pk=expense_id)
    comment = str(request.data.get("comment", "")).strip()
    try:
        if operation == "approve":
            expense = approve_expense(expense, request.user)
        elif operation == "reject":
            expense = reject_expense(expense, request.user, comment)
        else:
            expense = request_expense_changes(expense, request.user, comment)
        return Response(expense_to_dict(expense, detailed=True))
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_approve(request, expense_id):
    return _workflow_response(request, expense_id, "approve")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_reject(request, expense_id):
    return _workflow_response(request, expense_id, "reject")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_request_changes(request, expense_id):
    return _workflow_response(request, expense_id, "request_changes")


def _payment_queue(request, payment_status):
    expenses = Expense.objects.filter(
        organization__in=_accessible_organizations(request.user),
        status=Expense.Status.APPROVED,
        payment_status=payment_status,
        is_deleted=False,
    ).select_related("organization", "category", "paid_by", "submitted_by", "payment")
    expenses = [expense for expense in expenses if can_view(request.user, expense)]
    return Response(_paginate_items(request, expenses, payment_queue_to_dict))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unpaid_payments(request):
    return _payment_queue(request, Expense.PaymentStatus.UNPAID)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paid_payments(request):
    return _payment_queue(request, Expense.PaymentStatus.PAID)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def expense_mark_paid(request, expense_id):
    expense = get_object_or_404(Expense.objects.select_related("organization", "category", "paid_by", "submitted_by"), pk=expense_id)
    try:
        payment = mark_expense_paid(expense, request.user, request.data)
        return Response(payment_to_dict(payment), status=status.HTTP_201_CREATED)
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


def _reimbursement_visible(user, item):
    if item.expense_id:
        return can_view(user, item.expense) or can_process_reimbursement(user, item)
    return item.employee_id == user.id or can_process_reimbursement(user, item)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reimbursement_list(request):
    queryset = ReimbursementRequest.objects.select_related("employee", "expense", "expense__organization", "expense__category", "expense__paid_by", "expense__submitted_by").order_by("-requested_on", "-id")
    if request.query_params.get("status"):
        queryset = queryset.filter(status=request.query_params["status"])
    items = [item for item in queryset if _reimbursement_visible(request.user, item)]
    return Response(_paginate_items(request, items, reimbursement_to_dict))


def _reimbursement_action(request, reimbursement_id, action):
    reimbursement = get_object_or_404(ReimbursementRequest.objects.select_related("employee", "expense", "expense__organization"), pk=reimbursement_id)
    try:
        if action == "adjust":
            reimbursement = adjust_reimbursement_advance(reimbursement, request.user)
        elif action == "approve":
            reimbursement = approve_reimbursement(reimbursement, request.user)
        else:
            reimbursement = reject_reimbursement(reimbursement, request.user)
        return Response(reimbursement_to_dict(reimbursement))
    except ValidationError as exc:
        return Response(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_adjust_advance(request, reimbursement_id):
    return _reimbursement_action(request, reimbursement_id, "adjust")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_approve(request, reimbursement_id):
    return _reimbursement_action(request, reimbursement_id, "approve")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reimbursement_reject(request, reimbursement_id):
    return _reimbursement_action(request, reimbursement_id, "reject")
