import os
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.files import private_file_response

from inventory.models import Project
from organizations.services import has_permission, is_platform_admin
from organizations.models import OrganizationMembership

from .models import Expense, ExpenseCategory
from .serializers import ExpenseCategorySerializer, ExpenseSerializer


def _organization_context(request):
    project_id = request.headers.get("X-Project-ID")
    if not project_id:
        memberships = OrganizationMembership.objects.filter(user=request.user, is_active=True).select_related("organization")
        if memberships.count() != 1:
            raise ValidationError({"project": "X-Project-ID is required to resolve the organization."})
        return memberships.first().organization, None
    try:
        project = Project.objects.select_related("organization").get(pk=int(project_id))
    except (TypeError, ValueError):
        raise ValidationError({"project": "X-Project-ID must be a valid project id."})
    except Project.DoesNotExist as error:
        raise NotFound("Project not found.") from error
    if not is_platform_admin(request.user) and not OrganizationMembership.objects.filter(
        organization=project.organization, user=request.user, is_active=True
    ).exists():
        raise PermissionDenied("You do not have access to this project.")
    return project.organization, project


def _can_manage(request, organization, action):
    return has_permission(request.user, organization, f"expenses.{action}") or has_permission(
        request.user, organization, "expenses.manage_categories"
    )


def _envelope(data, success=True):
    return {"success": success, "data": data, "error": None}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def category_list(request):
    organization, project = _organization_context(request)
    categories = ExpenseCategory.objects.filter(organization=organization)
    if project:
        categories = categories.filter(Q(project=project) | Q(project__isnull=True))
    if request.query_params.get("is_active") in {"true", "1"}:
        categories = categories.filter(is_active=True)
    if request.method == "GET":
        return Response(_envelope(ExpenseCategorySerializer(categories, many=True).data))
    if not _can_manage(request, organization, "add"):
        raise PermissionDenied("You do not have permission to create expense categories.")
    serializer = ExpenseCategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    category = serializer.save(organization=organization, project=project)
    return Response(_envelope(ExpenseCategorySerializer(category).data), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def category_detail(request, category_id):
    organization, project = _organization_context(request)
    category = get_object_or_404(ExpenseCategory, pk=category_id, organization=organization)
    if project and category.project_id not in {None, project.id}:
        raise PermissionDenied("You do not have access to this project category.")
    if not _can_manage(request, organization, "edit"):
        raise PermissionDenied("You do not have permission to edit expense categories.")
    serializer = ExpenseCategorySerializer(category, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    category = serializer.save()
    return Response(_envelope(ExpenseCategorySerializer(category).data))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def expense_list(request):
    organization, project = _organization_context(request)
    if request.method == "GET":
        expenses = Expense.objects.filter(organization=organization).select_related("category", "submitted_by")
        if project:
            expenses = expenses.filter(project=project)
        serializer = ExpenseSerializer(expenses, many=True, context={"request": request})
        return Response(_envelope({"count": expenses.count(), "page": 1, "page_size": expenses.count(), "num_pages": 1, "results": serializer.data}))
    if not _can_manage(request, organization, "add"):
        raise PermissionDenied("You do not have permission to log expenses.")
    payload = request.data.copy()
    if "category" in payload and "category_id" not in payload:
        payload["category_id"] = request.data.get("category")
        payload.pop("category", None)
    serializer = ExpenseSerializer(data=payload, context={"action": request.data.get("action", "draft")})
    serializer.is_valid(raise_exception=True)
    category = serializer.validated_data["category"]
    if category.organization_id != organization.id or (project and category.project_id not in {None, project.id}):
        raise ValidationError({"category": "Category must belong to the active organization and project."})
    status_value = Expense.Status.PENDING_APPROVAL if request.data.get("action") == "submit" else Expense.Status.DRAFT
    expense = serializer.save(organization=organization, project=project, submitted_by=request.user, status=status_value)
    return Response(
        _envelope(ExpenseSerializer(expense, context={"request": request}).data),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def expense_receipt(request, expense_id):
    organization, project = _organization_context(request)
    expenses = Expense.objects.filter(organization=organization)
    if project:
        expenses = expenses.filter(project=project)
    expense = get_object_or_404(expenses, pk=expense_id)
    return private_file_response(expense.receipt, filename=os.path.basename(expense.receipt.name or "") or "receipt")
