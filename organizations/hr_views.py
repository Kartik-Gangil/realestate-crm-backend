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
from .hr_services import (cancel_leave, check_in, check_out, decide_leave, ensure_leave_balance,
                          leave_days, log_activity, validate_leave_date_range)
from .models import (AttendanceRecord, LeaveRequest, OrganizationHoliday, OrganizationMembership,
                     OrganizationRole, Permission, PerformanceReview)
from .services import get_organization_access, has_permission, is_organization_admin
from core.endpoint import crm_endpoint
from core.audit_context import set_audit_action
from system_settings.audit import log_audit


def _manage(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "role.edit"):
        raise PermissionDenied("Only organization admins and authorized platform users can manage this resource.")


def _dict_employee(employee):
    full_name = " ".join(part for part in (employee.first_name, employee.last_name) if part).strip()
    return {"id": employee.id, "employee_id": employee.employee_id,
            "name": full_name or employee.user.get_full_name() or employee.user.email}


def _role(role):
    return {"id": role.id, "name": role.name, "code": role.code, "description": role.description, "is_system": role.is_system,
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


def _permission_codes(role):
    return sorted(
        f"{permission.module}.{permission.action}"
        for permission in role.permissions.all()
    )


def _permission_change_audit(request, organization, role, before, after):
    before_set, after_set = set(before), set(after)
    log_audit(
        request=request,
        organization=organization,
        module="roles",
        action="permissions",
        details={
            "added": sorted(after_set - before_set),
            "removed": sorted(before_set - after_set),
        },
        target=role,
        payload_before={"permissions": sorted(before)},
        payload_after={"permissions": sorted(after)},
    )


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "role.view", "POST": "role.add"})
def roles(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET":
        return Response([_role(item) for item in OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions")])
    _manage(access)
    name, code = str(request.data.get("name", "")).strip(), str(request.data.get("code", "")).strip().lower()
    description = str(request.data.get("description", "")).strip()
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
            role = OrganizationRole.objects.create(organization=access.organization, name=name, code=code, description=description)
            role.permissions.set(permissions)
            employee = access.membership or access.organization.memberships.first()
            if employee: log_activity(organization=access.organization, employee=employee, action="role_created", actor=request.user, module="roles", details={"role": code})
    except IntegrityError:
        return Response({"name": "Role name and code must be unique within this organization."}, status=400)
    return Response(_role(role), status=201)


@crm_endpoint(["GET", "PATCH", "PUT", "DELETE"], scope="organization", permissions={"GET": "role.view", "PATCH": "role.edit", "PUT": "role.edit", "DELETE": "role.delete"})
def role_detail(request, organization_slug, role_id):
    access = get_organization_access(request.user, organization_slug)
    role = get_object_or_404(OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions"), pk=role_id)
    if request.method == "GET": return Response(_role(role))
    _manage(access)
    if role.is_system and role.code == "admin" and (
        request.method == "DELETE" or any(field in request.data for field in ("name", "code", "permission_ids"))
    ):
        return Response({"code": "system_role_locked", "detail": "The system Admin role is locked."}, status=403)
    if request.method == "DELETE":
        if access.organization.memberships.filter(organization_role=role).exists():
            return Response({"role": "Reassign employees before deleting this role."}, status=409)
        if not request.data.get("confirmation"):
            return Response({"code": "confirmation_required"}, status=409)
        role.delete()
        return Response(status=204)
    for field in ("name", "code", "description"):
        if field in request.data: setattr(role, field, str(request.data[field]).strip())
    if "permission_ids" in request.data:
        before_permissions = _permission_codes(role)
        permission_ids, permission_error = _validated_permission_ids(request.data["permission_ids"])
        if permission_error:
            return Response({"permission_ids": permission_error}, status=400)
        selected = list(Permission.objects.filter(pk__in=permission_ids))
        if len(selected) != len(permission_ids): return Response({"permission_ids": "Use valid unique permission IDs."}, status=400)
        role.permissions.set(selected)
        _permission_change_audit(request, access.organization, role, before_permissions, _permission_codes(role))
    try: role.save()
    except IntegrityError: return Response({"name": "Role name and code must be unique within this organization."}, status=400)
    employee = access.membership or access.organization.memberships.first()
    if employee: log_activity(organization=access.organization, employee=employee, action="role_updated", actor=request.user, module="roles", details={"role": role.code})
    return Response(_role(role))


@crm_endpoint(["PUT"], scope="organization", permissions={"PUT": "role.edit"})
def role_permissions(request, organization_slug, role_id):
    access = get_organization_access(request.user, organization_slug)
    role = get_object_or_404(OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions"), pk=role_id)
    if role.is_system and role.code == "admin":
        return Response({"code": "system_role_locked", "detail": "The system Admin role is locked."}, status=403)
    permission_ids, permission_error = _validated_permission_ids(request.data.get("permission_ids", []))
    if permission_error:
        return Response({"permission_ids": permission_error}, status=400)
    selected = list(Permission.objects.filter(pk__in=permission_ids))
    if len(selected) != len(permission_ids):
        return Response({"permission_ids": "Use valid unique permission IDs."}, status=400)
    before_permissions = _permission_codes(role)
    role.permissions.set(selected)
    _permission_change_audit(request, access.organization, role, before_permissions, _permission_codes(role))
    return Response(_role(role))


@crm_endpoint(["GET"], scope="organization")
def permissions(request, organization_slug):
    get_organization_access(request.user, organization_slug)
    return Response([{
        "id": item.id,
        "module": item.module,
        "action": item.action,
        "code": item.code,
        "name": item.name,
        "scope": item.scope,
        "actions": [item.action],
    } for item in Permission.objects.all()])


def _attendance(record):
    return {"id": record.id, "employee": _dict_employee(record.employee), "attendance_date": record.attendance_date,
            "check_in": record.check_in, "check_out": record.check_out, "total_hours": record.total_hours,
            "status": record.status}


@crm_endpoint(["GET"], scope="organization", permissions={"GET": "attendance.view"})
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


@crm_endpoint(["POST"], scope="organization", permissions={"POST": "attendance.add"})
def attendance_check_in(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    employee_id = request.data.get("employee", access.membership.id if access.membership else None)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if not access.is_platform and employee != access.membership and not has_permission(request.user, access.organization, "attendance.edit"): raise PermissionDenied("You can only check in for yourself.")
    try: record = check_in(organization=access.organization, employee=employee, actor=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(_attendance(AttendanceRecord.objects.select_related("employee__user").get(pk=record.pk)), status=201)


@crm_endpoint(["POST"], scope="organization", permissions={"POST": "attendance.edit"})
def attendance_check_out(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    employee_id = request.data.get("employee", access.membership.id if access.membership else None)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if not access.is_platform and employee != access.membership and not has_permission(request.user, access.organization, "attendance.edit"): raise PermissionDenied("You can only check out for yourself.")
    try: record = check_out(organization=access.organization, employee=employee, actor=request.user)
    except ValidationError as error: return _validation_response(error)
    return Response(_attendance(AttendanceRecord.objects.select_related("employee__user").get(pk=record.pk)))


def _leave(leave):
    return {"id": leave.id, "employee": _dict_employee(leave.employee), "leave_type": leave.leave_type,
            "from_date": leave.from_date, "to_date": leave.to_date, "days": leave.days, "reason": leave.reason,
            "total_days": leave.days, "status": leave.status, "rejection_reason": leave.rejection_reason,
            "approved_by": leave.approved_by_id}


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "settings.view", "POST": "settings.edit"})
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


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "leave.view", "POST": "leave.add"})
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
    if not access.is_platform and employee != access.membership and not has_permission(request.user, access.organization, "leave.edit"): raise PermissionDenied("You can only apply for your own leave.")
    try:
        from_date, to_date = parse_date(str(request.data["from_date"])), parse_date(str(request.data["to_date"]))
        if not from_date or not to_date: raise ValidationError({"from_date": "Use ISO dates (YYYY-MM-DD)."})
        validate_leave_date_range(from_date, to_date)
        leave_type = str(request.data["leave_type"]).strip().lower()
        if leave_type == LeaveRequest.LeaveType.EARNED:
            leave_type = LeaveRequest.LeaveType.PAID
        if leave_type not in {LeaveRequest.LeaveType.CASUAL, LeaveRequest.LeaveType.SICK, LeaveRequest.LeaveType.PAID}:
            raise ValidationError({"leave_type": "Use casual, sick, or paid."})
        days = leave_days(access.organization, from_date, to_date)
        if days <= 0:
            raise ValidationError({"date_range": "The selected range contains no working days."})
        overlap = LeaveRequest.objects.filter(
            organization=access.organization,
            employee=employee,
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            from_date__lte=to_date,
            to_date__gte=from_date,
        ).exists()
        if overlap:
            raise ValidationError({"date_range": "This leave overlaps a pending or approved request."})
        balance = ensure_leave_balance(
            organization=access.organization,
            employee=employee,
            leave_type=leave_type,
            year=from_date.year,
        )
        if balance.remaining_days < days:
            raise ValidationError({"balance": "Insufficient leave balance."})
        leave = LeaveRequest.objects.create(organization=access.organization, employee=employee, leave_type=leave_type, from_date=from_date, to_date=to_date, days=days, reason=request.data["reason"])
        log_activity(organization=access.organization, employee=employee, action="leave_applied", actor=request.user, module="leave", details={"leave_id": leave.id, "days": days})
    except (KeyError, ValidationError) as error: return _validation_response(error)
    return Response(_leave(LeaveRequest.objects.select_related("employee__user").get(pk=leave.pk)), status=201)


def _leave_balance(balance):
    return {
        "id": balance.id,
        "employee": _dict_employee(balance.employee),
        "leave_type": balance.leave_type,
        "year": balance.year,
        "allocated_days": balance.allocated_days,
        "used_days": balance.used_days,
        "remaining_days": balance.remaining_days,
    }


@crm_endpoint(["GET"], scope="organization", permissions={"GET": "leave.view"})
def leave_balances(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    year = timezone.localdate().year
    results = []
    for employee in _employees_for_access(access):
        for leave_type in (LeaveRequest.LeaveType.CASUAL, LeaveRequest.LeaveType.SICK, LeaveRequest.LeaveType.PAID):
            results.append(_leave_balance(ensure_leave_balance(
                organization=access.organization,
                employee=employee,
                leave_type=leave_type,
                year=year,
            )))
    return Response({"year": year, "results": results})


@crm_endpoint(["GET", "PATCH"], scope="organization", permissions={"GET": "leave.view", "PATCH": "leave.edit"})
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
    if "leave_type" in request.data: leave.leave_type = request.data["leave_type"]
    if "from_date" in request.data: leave.from_date = parse_date(str(request.data["from_date"]))
    if "to_date" in request.data: leave.to_date = parse_date(str(request.data["to_date"]))
    if "reason" in request.data: leave.reason = request.data["reason"]
    try:
        if not leave.from_date or not leave.to_date:
            raise ValidationError({"from_date": "Use ISO dates (YYYY-MM-DD)."})
        validate_leave_date_range(leave.from_date, leave.to_date)
        leave.days = leave_days(access.organization, leave.from_date, leave.to_date)
        leave.full_clean()
    except ValidationError as error:
        return _validation_response(error)
    leave.save()
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
    try:
        set_audit_action(request, "approve" if approved else "reject")
        leave = decide_leave(leave=leave, actor_membership=access.membership, actor=request.user, approved=approved, rejection_reason=str(request.data.get("rejection_reason", "")))
    except ValidationError as error: return _validation_response(error)
    set_audit_action(request, None)
    return Response(_leave(LeaveRequest.objects.select_related("employee__user").get(pk=leave.pk)))
@crm_endpoint(["POST"], scope="organization", permissions={"POST": "leave.approve"})
def leave_approve(request, organization_slug, leave_id): return _leave_action(request, organization_slug, leave_id, True)
@crm_endpoint(["POST"], scope="organization", permissions={"POST": "leave.approve"})
def leave_reject(request, organization_slug, leave_id): return _leave_action(request, organization_slug, leave_id, False)
@crm_endpoint(["POST"], scope="organization", permissions={"POST": "leave.edit"})
def leave_cancel(request, organization_slug, leave_id):
    access = get_organization_access(request.user, organization_slug)
    leave = get_object_or_404(
        LeaveRequest.objects.filter(
            organization=access.organization,
            employee__in=_employees_for_access(access),
        ),
        pk=leave_id,
    )
    leave = cancel_leave(leave=leave, actor_membership=access.membership, actor=request.user)
    return Response(_leave(LeaveRequest.objects.select_related("employee__user", "approved_by").get(pk=leave.pk)))


def _review_dict(review):
    return {
        "id": review.id,
        "employee_id": review.employee_id,
        "quarter": review.quarter,
        "rating": review.rating,
        "comments": review.comments,
        "reviewer_id": review.reviewer_id,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "updated_at": review.updated_at.isoformat() if review.updated_at else None,
    }


def _can_review(access, employee):
    return bool(
        access.is_platform
        or is_organization_admin(access.membership)
        or (access.membership and access.membership.organization_role and access.membership.organization_role.code == "hr-admin")
        or (access.membership and employee.reporting_manager_id == access.membership.id)
    )


@crm_endpoint(["GET", "POST", "PATCH"], scope="organization", permissions={"GET": "employees.view", "POST": "employees.edit", "PATCH": "employees.edit"})
def performance(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(OrganizationMembership.objects.select_related("reporting_manager", "user"), organization=access.organization, pk=employee_id)
    if request.method == "GET":
        if employee.user_id != request.user.id and not _can_review(access, employee):
            raise PermissionDenied("You can only view your own or your team's reviews.")
        reviews = PerformanceReview.objects.filter(employee=employee).select_related("reviewer")
        return Response({"results": [_review_dict(item) for item in reviews]})
    if not _can_review(access, employee):
        raise PermissionDenied("Only the reporting manager or HR Admin can submit reviews.")
    review_id = request.data.get("review_id")
    if review_id:
        review = get_object_or_404(PerformanceReview, pk=review_id, employee=employee, organization=access.organization)
        if review.reviewer_id != request.user.id and not (access.membership and access.membership.organization_role and access.membership.organization_role.code == "hr-admin") and not is_organization_admin(access.membership):
            raise PermissionDenied("Only the reviewer or HR Admin can edit this review.")
        before = _review_dict(review)
        if "rating" in request.data:
            review.rating = request.data["rating"]
        if "comments" in request.data:
            review.comments = str(request.data["comments"])
        try:
            review.full_clean()
            review.save(update_fields=["rating", "comments", "updated_at"])
        except ValidationError as error:
            return _validation_response(error)
        log_audit(request=request, organization=access.organization, module="performance_reviews", action="update", target=review, payload_before=before, payload_after=_review_dict(review))
        return Response(_review_dict(review))
    review = PerformanceReview(
        organization=access.organization,
        employee=employee,
        quarter=str(request.data.get("quarter", "")),
        rating=request.data.get("rating", request.data.get("overallRating", 0)),
        comments=str(request.data.get("comments", request.data.get("feedback", ""))),
        reviewer=request.user,
    )
    try:
        review.full_clean()
        review.save()
    except (ValidationError, IntegrityError) as error:
        return _validation_response(error)
    return Response(_review_dict(review), status=201)
