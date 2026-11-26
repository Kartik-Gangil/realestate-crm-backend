import os
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.files import private_file_response

from .employee_serializers import DepartmentSerializer, EmployeeCreateSerializer, EmployeeUpdateSerializer
from .models import Department, Organization, OrganizationActivity, OrganizationMembership, OrganizationRole, ProjectAssignment
from .services import (can_manage_account, effective_tab_permissions, ensure_default_roles,
                       get_organization_access, has_permission, is_organization_admin,
                       membership_permission_codes)
from inventory.models import Project
from core.endpoint import crm_endpoint
from core.audit_context import reset_audit_signal_suppression, set_audit_action, suppress_audit_signals
from system_settings.audit import log_audit, log_bulk_audit
from users.security import is_developer
from users.views import PasswordResetDeliveryError, send_password_reset_email


def _validation_response(error):
    if hasattr(error, "message_dict"):
        details = error.message_dict
    elif hasattr(error, "detail"):
        details = error.detail
    else:
        details = {"detail": [str(error)]}
    return Response(details, status=status.HTTP_400_BAD_REQUEST)


def _require_employee_management(access, permission="employees.edit"):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, permission):
        raise PermissionDenied("Only organization admins, managers, and authorized platform users can manage employees.")


def _require_users_management(request, access):
    """Keep user-account administration separate from the employee directory."""
    path_segments = {segment for segment in request.path.split("/") if segment}
    if "users" in path_segments and not access.is_platform and not has_permission(
        access.membership.user, access.organization, "users.manage"
    ):
        raise PermissionDenied("User administration requires users.manage.")


def _require_role_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "role.edit"):
        raise PermissionDenied("Only organization admins and authorized platform users can change employee roles or access scopes.")


def _employees_for_access(access):
    queryset = OrganizationMembership.objects.filter(
        organization=access.organization,
        user__developer_account__isnull=True,
    ).select_related(
        "user", "department", "reporting_manager__user", "organization", "organization_role"
    ).prefetch_related("assigned_projects")
    if (
        access.is_platform
        or is_organization_admin(access.membership)
        or access.membership.access_scope == OrganizationMembership.AccessScope.ALL
        or has_permission(access.membership.user, access.organization, "employees.view_team")
    ):
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


def _assert_account_level(request, access, target_user):
    if is_developer(target_user):
        raise PermissionDenied({"code": "account_level_forbidden", "detail": "Developer accounts cannot be changed through this API."})
    if not can_manage_account(request.user, target_user, access.organization):
        raise PermissionDenied({"code": "account_level_forbidden", "detail": "You cannot change an account above your level."})


def _assert_developer_mutation_forbidden(access, employee_id):
    if OrganizationMembership.objects.filter(
        pk=employee_id,
        organization=access.organization,
        user__developer_account__isnull=False,
    ).exists() or (
        not OrganizationMembership.objects.filter(pk=employee_id, organization=access.organization).exists()
        and get_user_model().objects.filter(pk=employee_id, developer_account__isnull=False).exists()
    ):
        raise PermissionDenied({"code": "account_level_forbidden", "detail": "Developer accounts cannot be changed here."})


def _developer_user_dict(user, organization):
    return {
        "id": user.id,
        "user_id": user.id,
        "employee_id": None,
        "name": "Developer",
        "first_name": "Developer",
        "last_name": "",
        "email": user.email,
        "role": "Developer",
        "role_id": None,
        "role_name": "Developer",
        "status": "Active" if user.is_active else "Inactive",
        "is_active": user.is_active,
        "is_developer": True,
        "organization": organization.slug,
        "assigned_projects": [],
        "project_ids": [],
    }


def _employee_to_dict(employee, request=None, detailed=False):
    photo = f"/api/organizations/{employee.organization.slug}/employees/{employee.id}/photo/" if employee.profile_photo else None
    name_first = employee.first_name or employee.user.first_name
    name_last = employee.last_name or employee.user.last_name
    permission_codes = {f"{module}.{action}" for module, action in membership_permission_codes(employee)}
    can_process_expense_payment = bool(permission_codes & {"expenses.mark_paid", "expenses.process_payment"})
    data = {
        "id": employee.id,
        "user_id": employee.user_id,
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
        "role_id": employee.organization_role_id,
        "role_name": employee.organization_role.name if employee.organization_role_id else employee.role,
        "role_code": employee.organization_role.code if employee.organization_role_id else employee.role,
        "can_process_expense_payment": can_process_expense_payment,
        "access_scope": employee.access_scope,
        "project_ids": list(employee.assigned_projects.values_list("id", flat=True)),
        "status": "active" if employee.is_active else "inactive",
        "is_active": employee.is_active,
        "date_of_joining": employee.date_of_joining.isoformat() if employee.date_of_joining else None,
    }
    can_view_compensation = bool(
        request
        and (
            is_organization_admin(get_organization_access(request.user, employee.organization.slug).membership)
            or has_permission(request.user, employee.organization, "employees.view_compensation")
        )
    )
    if detailed:
        data.update({
            "address": employee.address,
            "date_of_birth": employee.date_of_birth.isoformat() if employee.date_of_birth else None,
            "gender": employee.gender,
            "employment_type": employee.employment_type,
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
        if can_view_compensation:
            data["salary"] = str(employee.salary) if employee.salary is not None else None
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def member_tab_permissions(request, organization_slug, employee_id):
    """Return role-derived tab access for a member.

    Per-member tab overrides were removed in favor of organization roles. The
    edit form still needs this read model to show selected, role-allowed, and
    effective access consistently.
    """
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    tabs = effective_tab_permissions(employee, is_platform=access.is_platform)
    permission_codes = sorted(
        f"{module}.{action}"
        for module, action in membership_permission_codes(employee)
    )
    return Response({
        "selected_tab_permissions": tabs,
        "role_allowed_tabs": tabs,
        "effective_tab_permissions": tabs,
        "selected_permission_codes": permission_codes,
        "role_permission_codes": permission_codes,
    })


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
        if value is None or value == "":
            resolved["department"] = None
        else:
            department = Department.objects.filter(
                organization=organization,
                is_active=True,
            ).filter(Q(pk=value) if str(value).isdigit() else Q(name__iexact=str(value))).first()
            if department is None:
                raise ValidationError({"department": "Use an active department ID or name in this organization."})
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
    if "project_ids" in data:
        ids = data["project_ids"]
        if len(ids) != len(set(ids)):
            raise ValidationError({"project_ids": "Project IDs must not contain duplicates."})
        selected = list(Project.objects.filter(pk__in=ids, organization=organization))
        if len(selected) != len(ids):
            raise ValidationError({"project_ids": "Use projects in this organization."})
        resolved["project_ids"] = selected
    return resolved


def _sync_project_assignments(employee, projects, assigned_by, request=None):
    project_ids = {project.id for project in projects}
    removed = list(ProjectAssignment.objects.filter(membership=employee).exclude(project_id__in=project_ids))
    if removed:
        token = suppress_audit_signals()
        try:
            ProjectAssignment.objects.filter(pk__in=[item.pk for item in removed]).delete()
        finally:
            reset_audit_signal_suppression(token)
        log_bulk_audit(
            request=request, module="employees", action="bulk_delete", instances=removed,
            organization=employee.organization, changed_values={"deleted": True},
        )
    if not employee.organization_role_id:
        return
    for project in projects:
        ProjectAssignment.objects.update_or_create(
            membership=employee,
            project=project,
            defaults={"role": employee.organization_role, "assigned_by": assigned_by},
        )


def _assert_role_change_allowed(access, role):
    if (
        access.is_platform
        or role is None
        or has_permission(access.membership.user, access.organization, "role.edit")
        or has_permission(access.membership.user, access.organization, "users.manage")
    ):
        return
    raise PermissionDenied("Role assignment requires role.edit.")


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "employees.view", "POST": "employees.add"})
def employee_list(request, organization_slug):
    access = get_organization_access(request.user, organization_slug)
    _require_users_management(request, access)
    if request.method == "GET":
        try:
            employees = _filter_employees(_employees_for_access(access), request.query_params, access.organization)
            count, page, page_size, results = _paginate(employees, request.query_params)
            results = list(results)
        except ValidationError as error:
            return _validation_response(error)
        developers = []
        if request.path.rstrip("/").endswith("/users"):
            developers = [
                _developer_user_dict(user, access.organization)
                for user in get_user_model().objects.filter(developer_account__isnull=False)
            ]
        return Response({"count": count, "next": _page_url(request, page + 1, page_size) if page * page_size < count else None,
                         "previous": _page_url(request, page - 1, page_size) if page > 1 else None,
                         "results": [item if isinstance(item, dict) else _employee_to_dict(item, request) for item in results],
                         "developers": developers})

    _require_employee_management(access, "employees.add")
    serializer = EmployeeCreateSerializer(data=request.data, context={"organization": access.organization})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    assigned_role = None
    if data.get("role_id") is not None:
        assigned_role = OrganizationRole.objects.filter(
            organization=access.organization, pk=data["role_id"]
        ).first()
        if assigned_role is None:
            return Response({"role_id": ["Use a role from this organization."]}, status=status.HTTP_400_BAD_REQUEST)
        data.pop("role_id")
    _assert_role_change_allowed(access, assigned_role)
    can_manage_user_access = access.is_platform or has_permission(
        access.membership.user,
        access.organization,
        "users.manage",
    )
    if not can_manage_user_access and not has_permission(access.membership.user, access.organization, "settings.edit"):
        if data["access_scope"] != OrganizationMembership.AccessScope.ALL or data.get("custom_scope_memberships") or data.get("custom_scope_departments") or data.get("project_ids") is not None:
            raise PermissionDenied("Only organization admins can assign employee access scopes.")
    try:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=access.organization.pk)
            relations = _resolve_relations(data, organization)
            user = data["user"]
            user_was_created = user is None
            if user is None:
                token = suppress_audit_signals()
                try:
                    user = get_user_model().objects.create_user(
                        username=data["email"], email=data["email"], password=data["temporary_password"],
                        first_name=data["first_name"], last_name=data.get("last_name", ""),
                        is_staff=False, is_superuser=False,
                    )
                finally:
                    reset_audit_signal_suppression(token)
            else:
                _assert_account_level(request, access, user)
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
            employee.organization_role = (
                OrganizationRole.objects.get(organization=organization, pk=assigned_role.pk)
                if assigned_role is not None
                else ensure_default_roles(organization)[data["role"]]
            )
            for field in ("profile_photo", "mobile_number", "address", "date_of_birth", "gender", "designation",
                          "date_of_joining", "employment_type", "salary", "work_location", "access_scope"):
                if field in data:
                    setattr(employee, field, data[field])
            for field, value in relations.items():
                if field not in {"custom_scope_memberships", "custom_scope_departments", "project_ids"}:
                    setattr(employee, field, value)
            employee.full_clean()
            employee.save()
            if user_was_created:
                log_audit(
                    request=request, organization=organization, module="users", action="create", target=user,
                    payload_before={}, payload_after={"username": user.username, "email": user.email},
                )
            if "custom_scope_memberships" in relations:
                employee.custom_scope_memberships.set(relations["custom_scope_memberships"])
            if "custom_scope_departments" in relations:
                employee.custom_scope_departments.set(relations["custom_scope_departments"])
            if "project_ids" in relations:
                employee.assigned_projects.set(relations["project_ids"])
                _sync_project_assignments(employee, relations["project_ids"], request.user, request=request)
            _activity(employee=employee, action="employee_created", actor=request.user, details={"employee_id": employee.employee_id})
            _activity(employee=employee, action="role_assigned", actor=request.user, details={"role": employee.role})
    except (ValidationError, IntegrityError) as error:
        return _validation_response(error)
    employee = _employees_for_access(access).get(pk=employee.pk)
    return Response(_employee_to_dict(employee, request, detailed=True), status=status.HTTP_201_CREATED)


@crm_endpoint(["GET", "PATCH", "PUT"], scope="organization", permissions={"GET": "employees.view", "PATCH": "employees.edit", "PUT": "employees.edit"})
def employee_detail(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    _require_users_management(request, access)
    developer_membership = OrganizationMembership.objects.filter(
        pk=employee_id,
        organization=access.organization,
        user__developer_account__isnull=False,
    ).exists()
    legacy_developer_id = (
        not OrganizationMembership.objects.filter(pk=employee_id, organization=access.organization).exists()
        and get_user_model().objects.filter(pk=employee_id, developer_account__isnull=False).exists()
    )
    if developer_membership or legacy_developer_id:
        raise PermissionDenied({"code": "account_level_forbidden", "detail": "Developer accounts cannot be changed here."})
    employee = _employees_for_access(access).filter(pk=employee_id).first()
    if employee is None:
        raise Http404
    if request.method == "GET":
        return Response(_employee_to_dict(employee, request, detailed=True))
    _require_employee_management(access)
    _assert_account_level(request, access, employee.user)
    serializer = EmployeeUpdateSerializer(
        data=request.data,
        context={"organization": access.organization, "employee": employee},
    )
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if not data:
        return Response({"detail": "At least one editable user field is required."}, status=status.HTTP_400_BAD_REQUEST)
    protected = set(request.data) - set(serializer.fields)
    if protected:
        return Response({field: ["This field cannot be updated."] for field in protected}, status=status.HTTP_400_BAD_REQUEST)
    role_or_scope = {"role", "role_id", "access_scope", "custom_scope_memberships", "project_ids"} & set(data)
    if role_or_scope:
        _require_role_management(access)
    assigned_role = None
    if "role_id" in data:
        assigned_role = OrganizationRole.objects.filter(
            organization=access.organization,
            pk=data["role_id"],
        ).first()
        if assigned_role is None:
            return Response(
                {"role_id": ["Use a role from this organization."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data.pop("role_id")
    try:
        with transaction.atomic():
            employee = OrganizationMembership.objects.select_for_update().select_related("user").get(
                pk=employee.pk, organization=access.organization
            )
            new_email = data.pop("email", None)
            if new_email is not None:
                new_email = new_email.lower()
                duplicate = get_user_model().objects.filter(email__iexact=new_email).exclude(pk=employee.user_id).exists()
                if duplicate:
                    raise ValidationError({"email": "An account with this email already exists."})
            relations = _resolve_relations(data, access.organization, employee)
            changed = []
            for field, value in data.items():
                if field in {"department", "reporting_manager", "custom_scope_memberships", "custom_scope_departments", "project_ids"}:
                    continue
                if getattr(employee, field) != value:
                    setattr(employee, field, value)
                    changed.append(field)
            if "role" in changed and assigned_role is None:
                employee.organization_role = ensure_default_roles(access.organization)[employee.role]
                changed.append("organization_role")
            if assigned_role is not None and employee.organization_role_id != assigned_role.id:
                employee.organization_role = assigned_role
                changed.append("organization_role")
            for field, value in relations.items():
                if field not in {"custom_scope_memberships", "project_ids"} and getattr(employee, field) != value:
                    setattr(employee, field, value)
                    changed.append(field)
            employee.full_clean()
            role_changed = bool({"role", "organization_role"} & set(changed))
            previous_audit_action = getattr(request, "_audit_action", None)
            if role_changed:
                set_audit_action(request, "role_change")
            try:
                employee.save()
            finally:
                set_audit_action(request, previous_audit_action)
            if "custom_scope_memberships" in relations:
                employee.custom_scope_memberships.set(relations["custom_scope_memberships"])
                changed.append("custom_scope_memberships")
            if "custom_scope_departments" in relations:
                employee.custom_scope_departments.set(relations["custom_scope_departments"])
                changed.append("custom_scope_departments")
            if "project_ids" in relations:
                previous_project_ids = set(employee.assigned_projects.values_list("id", flat=True))
                next_project_ids = {project.id for project in relations["project_ids"]}
                employee.assigned_projects.set(relations["project_ids"])
                _sync_project_assignments(employee, relations["project_ids"], request.user, request=request)
                if previous_project_ids != next_project_ids:
                    changed.append("project_ids")
            if {"role", "organization_role"} & set(changed):
                assignments = list(ProjectAssignment.objects.filter(membership=employee))
                before = {str(item.pk): {"role_id": item.role_id, "assigned_by_id": item.assigned_by_id} for item in assignments}
                if assignments:
                    ProjectAssignment.objects.filter(pk__in=[item.pk for item in assignments]).update(role=employee.organization_role, assigned_by=request.user)
                    after = {str(item.pk): {"role_id": employee.organization_role_id, "assigned_by_id": request.user.pk} for item in assignments}
                    log_bulk_audit(
                        request=request, module="employees", action="bulk_update", instances=assignments,
                        organization=employee.organization, before=before, after=after,
                        changed_values={"role_id": employee.organization_role_id, "assigned_by_id": request.user.pk},
                    )
            if new_email is not None and employee.user.email.lower() != new_email:
                old_email = employee.user.email
                employee.user.email = new_email
                if employee.user.username == old_email:
                    employee.user.username = new_email
                employee.user.save(update_fields=["email", "username"])
                changed.append("email")
            if changed:
                _activity(employee=employee, action="employee_updated", actor=request.user, details={"fields": changed})
                if {"role", "organization_role"} & set(changed):
                    _activity(
                        employee=employee,
                        action="role_changed",
                        actor=request.user,
                        details={"role": employee.organization_role.code if employee.organization_role_id else employee.role},
                    )
                if {"access_scope", "custom_scope_memberships", "custom_scope_departments"} & set(changed):
                    _activity(employee=employee, action="access_scope_changed", actor=request.user,
                              details={"access_scope": employee.access_scope})
    except ValidationError as error:
        return _validation_response(error)
    employee = _employees_for_access(access).get(pk=employee.pk)
    return Response(_employee_to_dict(employee, request, detailed=True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_photo(request, organization_slug, employee_id):
    access = get_organization_access(request.user, organization_slug)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    return private_file_response(employee.profile_photo, filename=os.path.basename(employee.profile_photo.name or "") or "photo")


def _set_employee_active(request, organization_slug, employee_id, active):
    access = get_organization_access(request.user, organization_slug)
    _require_users_management(request, access)
    _require_employee_management(access)
    _assert_developer_mutation_forbidden(access, employee_id)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    _assert_account_level(request, access, employee.user)
    if employee.is_active == active:
        return Response({"status": ["Employee is already active." if active else "Employee is already inactive."]}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        employee.is_active = active
        previous_audit_action = getattr(request, "_audit_action", None)
        set_audit_action(request, "activate" if active else "deactivate")
        try:
            employee.save(update_fields=["is_active"])
        finally:
            set_audit_action(request, previous_audit_action)
        _activity(employee=employee, action="employee_activated" if active else "employee_deactivated", actor=request.user)
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
    """An organization admin can email a password-reset link to an employee."""
    access = get_organization_access(request.user, organization_slug)
    _require_users_management(request, access)
    _require_role_management(access)
    _assert_developer_mutation_forbidden(access, employee_id)
    employee = get_object_or_404(_employees_for_access(access), pk=employee_id)
    _assert_account_level(request, access, employee.user)
    try:
        send_password_reset_email(employee.user)
    except PasswordResetDeliveryError as error:
        return Response(
            {"code": "email_not_configured", "detail": str(error)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    _activity(employee=employee, action="employee_password_reset", actor=request.user)
    return Response({"detail": "Password reset link sent."}, status=status.HTTP_200_OK)


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
