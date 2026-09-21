from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .employee_serializers import DepartmentSerializer, EmployeeCreateSerializer, EmployeeUpdateSerializer
from .models import Department, Organization, OrganizationActivity, OrganizationMembership, OrganizationRole
from .services import ensure_default_roles, get_organization_access, has_permission
from system_settings.audit import log_audit


def _validation_response(error):
    if hasattr(error, "message_dict"):
        details = error.message_dict
    elif hasattr(error, "detail"):
        details = error.detail
    else:
        details = {"detail": [str(error)]}
    return Response(details, status=status.HTTP_400_BAD_REQUEST)


def _require_employee_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "employees.edit"):
        raise PermissionDenied("Only organization admins, managers, and authorized platform users can manage employees.")


def _require_role_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "settings.edit"):
        raise PermissionDenied("Only organization admins and authorized platform users can change employee roles or access scopes.")


def _employees_for_access(access):
    queryset = OrganizationMembership.objects.filter(organization=access.organization).select_related(
        "user", "department", "reporting_manager__user"
    )
    if access.is_platform or access.membership.access_scope == OrganizationMembership.AccessScope.ALL:
        return queryset
    if access.membership.access_scope == OrganizationMembership.AccessScope.OWN:
        return queryset.filter(pk=access.membership.pk)
    if access.membership.access_scope == OrganizationMembership.AccessScope.DEPARTMENT:
        if not access.membership.department_id:
            return queryset.filter(pk=access.membership.pk)
        return queryset.filter(Q(department_id=access.membership.department_id) | Q(pk=access.membership.pk))
    custom_ids = access.membership.custom_scope_memberships.values_list("id", flat=True)
    department_ids = access.membership.custom_scope_departments.values_list("id", flat=True)
    return queryset.filter(Q(pk=access.membership.pk) | Q(pk__in=custom_ids) | Q(department_id__in=department_ids))


def _employee_to_dict(employee, request=None, detailed=False):
    photo = employee.profile_photo.url if employee.profile_photo else None
    if photo and request:
        photo = request.build_absolute_uri(photo)
    name_first = employee.first_name or employee.user.first_name
    name_last = employee.last_name or employee.user.last_name
    data = {
        "id": employee.id,
        "employee_id": employee.employee_id,
        "name": " ".join(part for part in (name_first, name_last) if part).strip() or employee.user.email,
        "first_name": name_first,
        "last_name": name_last,
        "email": employee.user.email,
        "mobile_number": employee.mobile_number,
        "profile_photo": photo,
        "department": ({"id": employee.department_id, "name": employee.department.name} if employee.department_id else None),
        "designation": employee.designation,
        "reporting_manager": (
            {"id": employee.reporting_manager_id, "employee_id": employee.reporting_manager.employee_id,
             "name": " ".join(part for part in (employee.reporting_manager.first_name or employee.reporting_manager.user.first_name, employee.reporting_manager.last_name or employee.reporting_manager.user.last_name) if part).strip() or employee.reporting_manager.user.email}
            if employee.reporting_manager_id else None
        ),
        "role": employee.role,
        "project_ids": list(employee.projects.values_list("id", flat=True)),
        "access_scope": employee.access_scope,
        "status": "active" if employee.is_active else "inactive",
        "is_active": employee.is_active,
        "date_of_joining": employee.date_of_joining.isoformat() if employee.date_of_joining else None,
    }
    if detailed:
        data.update({
            "address": employee.address,
            "date_of_birth": employee.date_of_birth.isoformat() if employee.date_of_birth else None,
            "gender": employee.gender,
            "employment_type": employee.employment_type,
            "salary": str(employee.salary) if employee.salary is not None else None,
            "work_location": employee.work_location,
            "custom_scope_memberships": [
                {"id": item.id, "employee_id": item.employee_id,
                 "name": " ".join(part for part in (item.first_name or item.user.first_name, item.last_name or item.user.last_name) if part).strip() or item.user.email}
                for item in employee.custom_scope_memberships.select_related("user").all()
            ],
            "custom_scope_departments": [
                {"id": item.id, "name": item.name}
                for item in employee.custom_scope_departments.all()
            ],
            "joined_at": employee.joined_at.isoformat() if employee.joined_at else None,
        })
    return data


def _activity_to_dict(activity):
    return {
        "id": activity.id, "action": activity.action, "module": activity.module,
        "details": activity.details,
        "performed_by": ({"id": activity.performed_by_id, "email": activity.performed_by.email,
                          "name": activity.performed_by.get_full_name()} if activity.performed_by_id else None),
        "created_at": activity.created_at.isoformat(),
    }


def _activity(*, employee, action, actor, details=None):
    OrganizationActivity.objects.create(
        organization=employee.organization, employee=employee, action=action,
        details=details or {}, performed_by=actor,
    )


def _paginate(queryset, params):
    try:
        page = max(int(params.get("page", 1)), 1)
        page_size = min(max(int(params.get("page_size", 25)), 1), 100)
    except (TypeError, ValueError) as error:
        raise ValidationError({"page": "Page and page_size must be integers."}) from error
    count = queryset.count()
    return count, page, page_size, queryset[(page - 1) * page_size:page * page_size]


def _page_url(request, page, page_size):
    query = request.query_params.copy()
    query["page"] = page
    query["page_size"] = page_size
    return f"{request.build_absolute_uri(request.path)}?{query.urlencode()}"


def _filter_employees(queryset, params, organization):
    if status_value := params.get("status"):
        if status_value not in {"active", "inactive"}:
            raise ValidationError({"status": "Use 'active' or 'inactive'."})
        queryset = queryset.filter(is_active=status_value == "active")
    if department_id := params.get("department"):
        try:
            department_id = int(department_id)
        except (TypeError, ValueError) as error:
            raise ValidationError({"department": "Use a valid department ID."}) from error
        if not Department.objects.filter(pk=department_id, organization=organization).exists():
            raise ValidationError({"department": "Use a department in this organization."})
        queryset = queryset.filter(department_id=department_id)
    if designation := params.get("designation"):
        queryset = queryset.filter(designation__iexact=designation)
    if search := params.get("search"):
        queryset = queryset.filter(
            Q(employee_id__icontains=search) | Q(first_name__icontains=search) |
            Q(last_name__icontains=search) | Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) | Q(user__email__icontains=search) |
            Q(mobile_number__icontains=search) | Q(designation__icontains=search)
        )
    ordering = params.get("ordering", "employee_id")
    allowed = {"employee_id", "first_name", "designation", "date_of_joining", "joined_at"}
    raw = ordering.lstrip("-")
    if raw not in allowed:
        raise ValidationError({"ordering": "Use employee_id, first_name, designation, date_of_joining, or joined_at."})
    return queryset.order_by(ordering, "id")


def _resolve_relations(data, organization, employee=None):
    resolved = {}
    if "department" in data:
        value = data["department"]
        if value is None:
            resolved["department"] = None
        else:
            department = Department.objects.filter(pk=value, organization=organization, is_active=True).first()
            if department is None:
                raise ValidationError({"department": "Use an active department in this organization."})
            resolved["department"] = department
    if "reporting_manager" in data:
        value = data["reporting_manager"]
        if value is None:
            resolved["reporting_manager"] = None
        else:
            manager = OrganizationMembership.objects.select_related("user").filter(
                pk=value, organization=organization, is_active=True,
                role__in=[OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER],
            ).first()
            if manager is None:
                raise ValidationError({"reporting_manager": "Use an active manager in this organization."})
            if employee and manager.pk == employee.pk:
                raise ValidationError({"reporting_manager": "An employee cannot report to themselves."})
            resolved["reporting_manager"] = manager
    if "custom_scope_memberships" in data:
        ids = data["custom_scope_memberships"]
        if len(ids) != len(set(ids)):
            raise ValidationError({"custom_scope_memberships": "Employee IDs must not contain duplicates."})
        selected = list(OrganizationMembership.objects.filter(pk__in=ids, organization=organization))
        if len(selected) != len(ids):
            raise ValidationError({"custom_scope_memberships": "Use employees in this organization."})
        if employee and employee.pk in ids:
            raise ValidationError({"custom_scope_memberships": "An employee cannot add themselves to their custom scope."})
        resolved["custom_scope_memberships"] = selected
    if "custom_scope_departments" in data:
        ids = data["custom_scope_departments"]
        if len(ids) != len(set(ids)):
            raise ValidationError({"custom_scope_departments": "Department IDs must not contain duplicates."})
        selected = list(Department.objects.filter(pk__in=ids, organization=organization))
        if len(selected) != len(ids):
            raise ValidationError({"custom_scope_departments": "Use departments in this organization."})
        resolved["custom_scope_departments"] = selected
    return resolved


def _assert_role_change_allowed(access, role):
    if access.is_platform or has_permission(access.membership.user, access.organization, "settings.edit"):
        return
    if role != OrganizationMembership.Role.TELECALLER:
        raise PermissionDenied("Managers may only create employees with the telecaller role.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def employee_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET":
        try:
            employees = _filter_employees(_employees_for_access(access), request.query_params, access.organization)
            count, page, page_size, results = _paginate(employees, request.query_params)
        except ValidationError as error:
            return _validation_response(error)
        return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                         "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                         "results": [_employee_to_dict(item, request) for item in results]})

    _require_employee_management(access)
    serializer = EmployeeCreateSerializer(data=request.data, context={"organization": access.organization})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    _assert_role_change_allowed(access, data["role"])
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "settings.edit"):
        if data["access_scope"] != OrganizationMembership.AccessScope.ALL or data.get("custom_scope_memberships") or data.get("custom_scope_departments"):
            raise PermissionDenied("Only organization admins can assign employee access scopes.")
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=access.organization.pk)
            relations = _resolve_relations(data, organization)
            user = data["user"]
            if user is None:
                user = get_user_model().objects.create_user(
                    username=data["email"], email=data["email"], password=data["temporary_password"],
                    first_name=data["first_name"], last_name=data.get("last_name", ""),
                )
            # The counter is locked with the organization row.  The loop also
            # tolerates legacy employee IDs that pre-date this counter.
            organization.employee_sequence += 1
            employee_identifier = f"EMP{organization.employee_sequence:04d}"
            while OrganizationMembership.objects.filter(organization=organization, employee_id=employee_identifier).exists():
                organization.employee_sequence += 1
                employee_identifier = f"EMP{organization.employee_sequence:04d}"
            organization.save(update_fields=["employee_sequence"])
            employee = OrganizationMembership(
                organization=organization, user=user, employee_id=employee_identifier,
                role=data["role"], first_name=data["first_name"], last_name=data.get("last_name", ""),
            )
            employee.organization_role = ensure_default_roles(organization)[data["role"]]
            for field in ("profile_photo", "mobile_number", "address", "date_of_birth", "gender", "designation",
                          "date_of_joining", "employment_type", "salary", "work_location", "access_scope"):
                if field in data:
                    setattr(employee, field, data[field])
            for field, value in relations.items():
                if field not in {"custom_scope_memberships", "custom_scope_departments"}:
                    setattr(employee, field, value)
            employee.full_clean()
            employee.save()
            if "custom_scope_memberships" in relations:
                employee.custom_scope_memberships.set(relations["custom_scope_memberships"])
            if "custom_scope_departments" in relations:
                employee.custom_scope_departments.set(relations["custom_scope_departments"])
            if "project_ids" in data:
                employee.projects.set(data["project_ids"])
            _activity(employee=employee, action="employee_created", actor=request.user, details={"employee_id": employee.employee_id})
            _activity(employee=employee, action="role_assigned", actor=request.user, details={"role": employee.role})
            log_audit(
                request=request, organization=organization, module="users", action="user_created",
                details={"payload_before": None, "payload_after": _employee_to_dict(employee, detailed=True)}, target=employee,
            )
    except (ValidationError, IntegrityError) as error:
        return _validation_response(error)
    employee = _employees_for_access(access).get(pk=employee.pk)
    return Response(_employee_to_dict(employee, request, detailed=True), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAuthenticated])
def employee_detail(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if request.method == "GET":
        return Response(_employee_to_dict(employee, request, detailed=True))
    _require_employee_management(access)
    serializer = EmployeeUpdateSerializer(data=request.data, context={"organization": access.organization})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    protected = set(request.data) - set(serializer.fields)
    if protected:
        return Response({field: ["This field cannot be updated."] for field in protected}, status=status.HTTP_400_BAD_REQUEST)
    role_or_scope = {"role", "access_scope", "custom_scope_memberships"} & set(data)
    if role_or_scope:
        _require_role_management(access)
    try:
        with transaction.atomic():
            employee = OrganizationMembership.objects.select_for_update().select_related("user").get(
                pk=employee.pk, organization=access.organization
            )
            before = _employee_to_dict(employee, detailed=True)
            relations = _resolve_relations(data, access.organization, employee)
            changed = []
            for field, value in data.items():
                if field in {"department", "reporting_manager", "custom_scope_memberships", "custom_scope_departments", "project_ids"}:
                    continue
                if getattr(employee, field) != value:
                    setattr(employee, field, value)
                    changed.append(field)
            if "role" in changed:
                employee.organization_role = ensure_default_roles(access.organization)[employee.role]
                changed.append("organization_role")
            for field, value in relations.items():
                if field != "custom_scope_memberships" and getattr(employee, field) != value:
                    setattr(employee, field, value)
                    changed.append(field)
            employee.full_clean()
            employee.save()
            if "custom_scope_memberships" in relations:
                employee.custom_scope_memberships.set(relations["custom_scope_memberships"])
                changed.append("custom_scope_memberships")
            if "custom_scope_departments" in relations:
                employee.custom_scope_departments.set(relations["custom_scope_departments"])
                changed.append("custom_scope_departments")
            if "project_ids" in data:
                employee.projects.set(data["project_ids"])
                changed.append("project_ids")
            if changed:
                _activity(employee=employee, action="employee_updated", actor=request.user, details={"fields": changed})
                if "role" in changed:
                    _activity(employee=employee, action="role_changed", actor=request.user, details={"role": employee.role})
                if {"access_scope", "custom_scope_memberships", "custom_scope_departments"} & set(changed):
                    _activity(employee=employee, action="access_scope_changed", actor=request.user,
                              details={"access_scope": employee.access_scope})
                log_audit(
                    request=request, organization=access.organization, module="users", action="user_updated",
                    details={"payload_before": before, "payload_after": _employee_to_dict(employee, detailed=True)}, target=employee,
                )
    except ValidationError as error:
        return _validation_response(error)
    employee = _employees_for_access(access).get(pk=employee.pk)
    return Response(_employee_to_dict(employee, request, detailed=True))


def _set_employee_active(request, organization_slug, employee_id, active):
    access = get_organization_access(request.user, organization_slug)
    _require_employee_management(access)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    if employee.is_active == active:
        return Response({"status": ["Employee is already active." if active else "Employee is already inactive."]}, status=status.HTTP_400_BAD_REQUEST)
    employee.is_active = active
    employee.save(update_fields=["is_active"])
    if active:
        employee.user.is_active = True
        employee.user.save(update_fields=["is_active"])
    elif not employee.user.organization_memberships.filter(is_active=True).exists():
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active"])
    before = {"is_active": not active}
    after = {"is_active": active}
    _activity(employee=employee, action="employee_activated" if active else "employee_deactivated", actor=request.user)
    log_audit(
        request=request, organization=access.organization, module="users",
        action="user_activated" if active else "user_deactivated",
        details={"payload_before": before, "payload_after": after}, target=employee,
    )
    return Response(_employee_to_dict(employee, request, detailed=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def employee_activate(request, organization_slug, employee_id):
    return _set_employee_active(request, organization_slug, employee_id, True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def employee_deactivate(request, organization_slug, employee_id):
    return _set_employee_active(request, organization_slug, employee_id, False)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def employee_reset_password(request, organization_slug, employee_id):
    """An organization admin can issue a new temporary password for an employee."""
    access = get_organization_access(request.user, organization_slug)
    _require_role_management(access)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    temporary_password = request.data.get("temporary_password")
    if not isinstance(temporary_password, str) or len(temporary_password) < 8:
        return Response({"temporary_password": ["Use at least 8 characters."]}, status=status.HTTP_400_BAD_REQUEST)
    employee.user.set_password(temporary_password)
    employee.user.save(update_fields=["password"])
    _activity(employee=employee, action="employee_password_reset", actor=request.user)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_activity_history(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    try:
        history = employee.activity_history.select_related("performed_by").all()
        count, page, page_size, results = _paginate(history, request.query_params)
    except ValidationError as error:
        return _validation_response(error)
    return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                     "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                     "results": [_activity_to_dict(item) for item in results]})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def department_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    if request.method == "GET":
        departments = Department.objects.filter(organization=access.organization)
        if request.query_params.get("active_only") in {"true", "1"}:
            departments = departments.filter(is_active=True)
        return Response(DepartmentSerializer(departments, many=True).data)
    _require_employee_management(access)
    serializer = DepartmentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    department = serializer.save(organization=access.organization)
    return Response(DepartmentSerializer(department).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def department_detail(request, organization_slug, department_id):
    access = get_organization_access(request.user, organization_slug)
    department = get_object_or_404(Department, pk=department_id, organization=access.organization)
    if request.method == "GET":
        return Response(DepartmentSerializer(department).data)
    _require_employee_management(access)
    serializer = DepartmentSerializer(department, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    return Response(DepartmentSerializer(serializer.save()).data)
