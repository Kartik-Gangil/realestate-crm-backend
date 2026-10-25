from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .employee_views import _employees_for_access, _page_url, _paginate, _validation_response
from .hr_services import check_in, check_out, decide_leave, leave_days, log_activity
from .models import (AttendanceRecord, LeaveRequest, OrganizationHoliday, OrganizationMembership,
                     OrganizationRole, Permission)
from .services import get_organization_access, has_permission


def _manage(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "settings.edit"):
        raise PermissionDenied("Only organization admins and authorized platform users can manage this resource.")


def _dict_employee(employee):
    return {"id": employee.id, "employee_id": employee.employee_id,
            "name": employee.first_name or employee.user.get_full_name() or employee.user.email}


def _role(role):
    return {"id": role.id, "name": role.name, "code": role.code, "is_system": role.is_system,
            "permission_ids": list(role.permissions.values_list("id", flat=True)),
            "permissions": [item.code for item in role.permissions.all()]}


def _validated_permission_ids(raw_permission_ids):
    if not isinstance(raw_permission_ids, list):
        return None, "Provide permission_ids as a list of numeric IDs."

    permission_ids = []
    for raw_id in raw_permission_ids:
        if isinstance(raw_id, bool):
            return None, "Use valid unique permission IDs."
        if isinstance(raw_id, int):
            permission_id = raw_id
        elif isinstance(raw_id, str) and raw_id.strip().isdigit():
            permission_id = int(raw_id.strip())
        else:
            return None, "Use valid unique permission IDs."
        if permission_id <= 0:
            return None, "Use valid unique permission IDs."
        permission_ids.append(permission_id)

    if len(permission_ids) != len(set(permission_ids)):
        return None, "Use valid unique permission IDs."
    return permission_ids, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def roles(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET":
        return Response([_role(item) for item in OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions")])
    _manage(access)
    name, code = str(request.data.get("name", "")).strip(), str(request.data.get("code", "")).strip().lower()
    permission_ids = request.data.get("permission_ids", [])
    permission_ids, permission_error = _validated_permission_ids(permission_ids)
    if permission_error:
        return Response({"permission_ids": permission_error}, status=400)
    if not name or not code:
        return Response({"detail": "name and code are required."}, status=400)
    permissions = list(Permission.objects.filter(pk__in=permission_ids))
    if len(permissions) != len(set(permission_ids)):
        return Response({"permission_ids": "Use valid unique permission IDs."}, status=400)
    try:
        with transaction.atomic():
            role = OrganizationRole.objects.create(organization=access.organization, name=name, code=code)
            role.permissions.set(permissions)
            employee = access.membership or access.organization.memberships.first()
            if employee: log_activity(organization=access.organization, employee=employee, action="role_created", actor=request.user, module="roles", details={"role": code})
    except IntegrityError:
        return Response({"name": "Role name and code must be unique within this organization."}, status=400)
    return Response(_role(role), status=201)


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def role_detail(request, organization_slug, role_id):
    access = get_organization_access(request.user, organization_slug)
    role = get_object_or_404(OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions"), pk=role_id)
    if request.method == "GET": return Response(_role(role))
    _manage(access)
    if request.method == "DELETE":
        if access.organization.memberships.filter(organization_role=role).exists():
            return Response({"role": "Reassign employees before deleting this role."}, status=409)
        if not request.data.get("confirmation"):
            return Response({"code": "confirmation_required"}, status=409)
        role.delete(); 
        return Response(status=204)
    for field in ("name", "code"):
        if field in request.data: setattr(role, field, str(request.data[field]).strip())
    if "permission_ids" in request.data:
        permission_ids, permission_error = _validated_permission_ids(request.data["permission_ids"])
        if permission_error:
            return Response({"permission_ids": permission_error}, status=400)
        selected = list(Permission.objects.filter(pk__in=permission_ids))
        if len(selected) != len(permission_ids): return Response({"permission_ids": "Use valid unique permission IDs."}, status=400)
        role.permissions.set(selected)
    try: role.save()
    except IntegrityError: return Response({"name": "Role name and code must be unique within this organization."}, status=400)
    employee = access.membership or access.organization.memberships.first()
    if employee: log_activity(organization=access.organization, employee=employee, action="role_updated", actor=request.user, module="roles", details={"role": role.code})
    return Response(_role(role))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def permissions(request, organization_slug):
    get_organization_access(request.user, organization_slug)
    return Response([{
        "id": item.id,
        "module": item.module,
        "action": item.action,
        "code": item.code,
        "name": item.name,
        "actions": [item.action],
    } for item in Permission.objects.all()])


def _attendance(record):
    return {"id": record.id, "employee": _dict_employee(record.employee), "attendance_date": record.attendance_date,
            "check_in": record.check_in, "check_out": record.check_out, "total_hours": record.total_hours,
            "status": record.status}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    query = AttendanceRecord.objects.filter(organization=access.organization).select_related("employee__user", "employee__department")
    if not access.is_platform and access.membership.access_scope != OrganizationMembership.AccessScope.ALL:
        query = query.filter(employee__in=_employees_for_access(access))
    for key, field in (("date", "attendance_date"), ("status", "status"), ("employee", "employee_id"), ("department", "employee__department_id")):
        if value := request.query_params.get(key): query = query.filter(**{field: value})
    if request.query_params.get("date_from"): query = query.filter(attendance_date__gte=request.query_params["date_from"])
    if request.query_params.get("date_to"): query = query.filter(attendance_date__lte=request.query_params["date_to"])
    try: count, page, size, rows = _paginate(query, request.query_params)
    except ValidationError as error: return _validation_response(error)
    return Response({"count": count, "next": _page_url(request, page + 1, size) if page * size < count else None, "previous": _page_url(request, page - 1, size) if page > 1 else None, "results": [_attendance(x) for x in rows]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def attendance_check_in(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    employee_id = request.data.get("employee", access.membership.id if access.membership else None)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if not access.is_platform and employee != access.membership and access.membership.role not in {"admin", "manager"}: raise PermissionDenied("You can only check in for yourself.")
    try: record = check_in(organization=access.organization, employee=employee, actor=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(_attendance(AttendanceRecord.objects.select_related("employee__user").get(pk=record.pk)), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def attendance_check_out(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    employee_id = request.data.get("employee", access.membership.id if access.membership else None)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if not access.is_platform and employee != access.membership and access.membership.role not in {"admin", "manager"}: raise PermissionDenied("You can only check out for yourself.")
    try: record = check_out(organization=access.organization, employee=employee, actor=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(_attendance(AttendanceRecord.objects.select_related("employee__user").get(pk=record.pk)))


def _leave(leave):
    return {"id": leave.id, "employee": _dict_employee(leave.employee), "leave_type": leave.leave_type,
            "from_date": leave.from_date, "to_date": leave.to_date, "days": leave.days, "reason": leave.reason,
            "status": leave.status, "rejection_reason": leave.rejection_reason}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def holidays(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    query = OrganizationHoliday.objects.filter(organization=access.organization)
    if request.method == "GET":
        return Response([{"id": item.id, "name": item.name, "holiday_date": item.holiday_date, "source": item.source} for item in query])
    _manage(access)
    date = parse_date(str(request.data.get("holiday_date", "")))
    name = str(request.data.get("name", "")).strip()
    if not date or not name: return Response({"detail": "name and a valid holiday_date are required."}, status=400)
    try: holiday = OrganizationHoliday.objects.create(organization=access.organization, name=name, holiday_date=date, source="custom")
    except IntegrityError: return Response({"holiday_date": "A holiday already exists for this date."}, status=400)
    return Response({"id": holiday.id, "name": holiday.name, "holiday_date": holiday.holiday_date, "source": holiday.source}, status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def leaves(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    query = LeaveRequest.objects.filter(organization=access.organization).select_related("employee__user", "employee__department", "approved_by")
    if request.method == "GET":
        if not access.is_platform and access.membership.access_scope != OrganizationMembership.AccessScope.ALL: query = query.filter(employee__in=_employees_for_access(access))
        for key, field in (("employee", "employee_id"), ("leave_type", "leave_type"), ("status", "status"), ("department", "employee__department_id")):
            if value := request.query_params.get(key): query = query.filter(**{field: value})
        if request.query_params.get("date_from"): query = query.filter(to_date__gte=request.query_params["date_from"])
        if request.query_params.get("date_to"): query = query.filter(from_date__lte=request.query_params["date_to"])
        try: count, page, size, rows = _paginate(query, request.query_params)
        except ValidationError as error: return _validation_response(error)
        return Response({"count": count, "next": _page_url(request, page + 1, size) if page * size < count else None, "previous": _page_url(request, page - 1, size) if page > 1 else None, "results": [_leave(x) for x in rows]})
    employee = get_object_or_404(_employees_for_access(access), pk=request.data.get("employee", access.membership.id if access.membership else None))
    if not access.is_platform and employee != access.membership and access.membership.role not in {"admin", "manager"}: raise PermissionDenied("You can only apply for your own leave.")
    try:
        from_date, to_date = parse_date(str(request.data["from_date"])), parse_date(str(request.data["to_date"]))
        if not from_date or not to_date: raise ValidationError({"from_date": "Use ISO dates (YYYY-MM-DD)."})
        days = leave_days(access.organization, from_date, to_date)
        leave = LeaveRequest.objects.create(organization=access.organization, employee=employee, leave_type=request.data["leave_type"], from_date=from_date, to_date=to_date, days=days, reason=request.data["reason"])
        log_activity(organization=access.organization, employee=employee, action="leave_applied", actor=request.user, module="leave", details={"leave_id": leave.id, "days": days})
    except (KeyError, ValidationError) as error: return _validation_response(error)
    return Response(_leave(LeaveRequest.objects.select_related("employee__user").get(pk=leave.pk)), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def leave_detail(request, organization_slug, leave_id):
    access = get_organization_access(request.user, organization_slug)
    leave = get_object_or_404(
        LeaveRequest.objects.select_related("employee__user").filter(
            organization=access.organization,
            employee__in=_employees_for_access(access),
        ),
        pk=leave_id,
    )
    if request.method == "GET": return Response(_leave(leave))
    if leave.employee_id != getattr(access.membership, "id", None) or leave.status != LeaveRequest.Status.PENDING: raise PermissionDenied("Only the requesting employee may edit a pending leave request.")
    if any(key in request.data for key in ("status", "days", "approved_by", "approved_at")): return Response({"detail": "Workflow and calculated fields are server controlled."}, status=400)
    for key in ("leave_type", "from_date", "to_date", "reason"):
        if key in request.data: setattr(leave, key, request.data[key])
    leave.days = leave_days(access.organization, leave.from_date, leave.to_date); leave.full_clean(); leave.save()
    return Response(_leave(leave))


def _leave_action(request, slug, leave_id, approved):
    access = get_organization_access(request.user, slug)
    leave = get_object_or_404(
        LeaveRequest.objects.filter(
            organization=access.organization,
            employee__in=_employees_for_access(access),
        ),
        pk=leave_id,
    )
    try: leave = decide_leave(leave=leave, actor_membership=access.membership, actor=request.user, approved=approved, rejection_reason=str(request.data.get("rejection_reason", "")))
    except ValidationError as error: return _validation_response(error)
    return Response(_leave(LeaveRequest.objects.select_related("employee__user").get(pk=leave.pk)))
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_approve(request, organization_slug, leave_id): return _leave_action(request, organization_slug, leave_id, True)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_reject(request, organization_slug, leave_id): return _leave_action(request, organization_slug, leave_id, False)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_cancel(request, organization_slug, leave_id):
    access = get_organization_access(request.user, organization_slug)
    leave = get_object_or_404(
        LeaveRequest.objects.filter(
            organization=access.organization,
            employee__in=_employees_for_access(access),
        ),
        pk=leave_id,
    )
    if leave.employee_id != getattr(access.membership, "id", None) or leave.status != LeaveRequest.Status.PENDING: raise PermissionDenied("Only a pending request can be cancelled by its employee.")
    leave.status = LeaveRequest.Status.CANCELLED; leave.save(update_fields=["status", "updated_at"]); log_activity(organization=access.organization, employee=leave.employee, action="leave_cancelled", actor=request.user, module="leave", details={"leave_id": leave.id}); return Response(_leave(leave))
