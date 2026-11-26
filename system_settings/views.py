import os
import platform
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.files import private_file_response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as DrfValidationError
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission
from organizations.services import get_organization_access, has_permission
from inventory.models import Project
from .audit import log_audit
from .integrations import encrypt_secret
from .maintenance import clear_system_cache, health_check, rebuild_search_index
from .services import invalidate_system_parameter_cache, parameter_definition, validate_parameter_value, UnknownSystemParameter, ensure_organization_parameter_defaults, ensure_project_parameter_defaults
from .models import AuditLog, BackupRecord, IntegrationConfiguration, MasterData, MasterDataCategory, OrganizationSettings, SystemParameter
from .parameters import GENERAL_SETTINGS_CHOICES, PARAMETER_REGISTRY
from .permissions import require_developer_audit_access, require_organization_settings, require_platform_settings
from .serializers import AuditLogSerializer, BackupRecordSerializer, IntegrationSerializer, LegacyMasterDataSerializer, LegacySystemParameterSerializer, MasterDataSerializer, OrganizationSettingsSerializer, SystemParameterSerializer
from core.endpoint import crm_endpoint


def _page(query, request, serializer):
    try: page, size = max(int(request.query_params.get("page", 1)), 1), min(max(int(request.query_params.get("page_size", 25)), 1), 100)
    except ValueError: return Response({"detail": "page and page_size must be integers."}, status=400)
    count = query.count(); start = (page - 1) * size
    base = request.build_absolute_uri(request.path)
    return Response({"count": count, "next": f"{base}?page={page+1}&page_size={size}" if start + size < count else None, "previous": f"{base}?page={page-1}&page_size={size}" if page > 1 else None, "results": serializer(query[start:start+size], many=True).data})


def _org_access(request, slug, edit=False):
    access = get_organization_access(request.user, slug); require_organization_settings(access, request.user, edit); return access


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overview(request):
    require_platform_settings(request.user)
    last_backup = BackupRecord.objects.filter(status=BackupRecord.Status.COMPLETED).order_by("-completed_at").values_list("completed_at", flat=True).first()
    last_general = OrganizationSettings.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()
    return Response({"general_settings": {"configured": OrganizationSettings.objects.exists(), "last_updated": last_general},
                     "user_management": {"total_users": get_user_model().objects.count()}, "roles_permissions": {"total_roles": OrganizationRole.objects.count()},
                     "master_data": {"total_records": MasterData.objects.count()}, "integrations": {"active_integrations": IntegrationConfiguration.objects.filter(enabled=True).count()},
                     "system_parameters": {"total_parameters": SystemParameter.objects.count()}, "audit_logs": {"total_logs": AuditLog.objects.count()},
                     "backup_maintenance": {"last_backup": last_backup}})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_overview(request, organization_slug):
    access = _org_access(request, organization_slug)
    organization = access.organization
    organization_settings = OrganizationSettings.objects.filter(organization=organization).first()
    return Response({
        "organization_slug": organization.slug,
        "general_last_updated": organization_settings.updated_at if organization_settings else None,
        "timezone": organization_settings.timezone if organization_settings else "Asia/Kolkata",
        "total_users": OrganizationMembership.objects.filter(organization=organization).count(),
        "total_roles": OrganizationRole.objects.filter(organization=organization).count(),
        "total_master_records": MasterData.objects.filter(organization=organization).count(),
        "active_integrations": IntegrationConfiguration.objects.filter(organization=organization, enabled=True).count(),
        "total_parameters": SystemParameter.objects.filter(organization=organization).count(),
        "total_audit_logs": AuditLog.objects.filter(organization=organization).count(),
        "last_backup_date": None,
        "last_backup_size": "0 MB",
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organizations(request):
    require_platform_settings(request.user)
    query = Organization.objects.order_by("name")
    if search := request.query_params.get("search"): query = query.filter(name__icontains=search)
    return _page(query, request, lambda x, many: __import__('rest_framework').serializers.Serializer(x, many=many)) if False else Response({"count": query.count(), "results": list(query.values("id", "name", "slug", "is_active"))})


@crm_endpoint(
    ["GET", "PATCH", "PUT"],
    scope="organization",
    permissions={"GET": "settings.view", "PATCH": "settings.edit", "PUT": "settings.edit"},
)
def general_settings(request, organization_slug):
    access = _org_access(request, organization_slug, request.method in {"PATCH", "PUT"})
    obj, _ = OrganizationSettings.objects.get_or_create(organization=access.organization, defaults={"company_name": access.organization.name})
    if request.method == "GET": return Response(OrganizationSettingsSerializer(obj, context={"request": request}).data)
    serializer = OrganizationSettingsSerializer(obj, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        obj = serializer.save()
        if "company_name" in serializer.validated_data and obj.company_name and access.organization.name != obj.company_name:
            access.organization.name = obj.company_name; access.organization.save(update_fields=["name"])
    return Response(OrganizationSettingsSerializer(obj, context={"request": request}).data)


@crm_endpoint(["GET"], scope="organization", permissions={"GET": "settings.view"})
def general_settings_logo(request, organization_slug):
    access = _org_access(request, organization_slug, False)
    row = get_object_or_404(OrganizationSettings, organization=access.organization)
    return private_file_response(row.company_logo, filename=os.path.basename(row.company_logo.name or "") or "logo")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_info(request):
    require_platform_settings(request.user)
    from django import get_version
    return Response({"application_version": "0.1.0", "environment": settings.ENVIRONMENT_NAME, "django_version": get_version(), "python_version": platform.python_version(), "database_engine": settings.DATABASES["default"]["ENGINE"], "storage_backend": settings.DEFAULT_FILE_STORAGE if hasattr(settings, "DEFAULT_FILE_STORAGE") else "django default", "server_time": timezone.now(), "health": health_check()})


def _roles_payload(org):
    roles = OrganizationRole.objects.filter(organization=org).prefetch_related("permissions")
    return [{"id": r.id, "name": r.name, "code": r.code, "is_system": r.is_system, "permissions": [p.code for p in r.permissions.all()], "is_active": True} for r in roles]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def permissions(request, organization_slug):
    _org_access(request, organization_slug)
    grouped = {}
    for p in Permission.objects.all(): grouped.setdefault(p.module, []).append({"id": p.id, "code": p.code, "name": p.name, "action": p.action})
    return Response([{"module": module, "permissions": items} for module, items in grouped.items()])


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def role_mapping(request, organization_slug):
    access = _org_access(request, organization_slug, request.method == "POST")
    if request.method == "GET":
        rows = OrganizationMembership.objects.filter(organization=access.organization).select_related("user", "organization_role")
        return Response([{"id": x.id, "user": {"id": x.user_id, "email": x.user.email}, "role": {"id": x.organization_role_id, "code": x.organization_role.code if x.organization_role_id else None}} for x in rows])
    membership = get_object_or_404(OrganizationMembership, organization=access.organization, pk=request.data.get("membership_id")); role = get_object_or_404(OrganizationRole, organization=access.organization, pk=request.data.get("role_id"))
    if not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    membership.organization_role = role; membership.role = role.code if role.code in OrganizationMembership.Role.values else membership.role; membership.save(update_fields=["organization_role", "role"])
    return Response({"id": membership.id, "role_id": role.id})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def role_mapping_detail(request, organization_slug, membership_id):
    access = _org_access(request, organization_slug, True); membership = get_object_or_404(OrganizationMembership, organization=access.organization, pk=membership_id); role = get_object_or_404(OrganizationRole, organization=access.organization, pk=request.data.get("role_id"))
    if not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    membership.organization_role = role; membership.role = role.code if role.code in OrganizationMembership.Role.values else membership.role; membership.save(update_fields=["organization_role", "role"]); return Response({"id": membership.id, "role_id": role.id})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def access_matrix(request, organization_slug):
    access = _org_access(request, organization_slug); roles = OrganizationRole.objects.filter(organization=access.organization).prefetch_related("permissions")
    catalogue = list(Permission.objects.all()); modules = sorted(set(p.module for p in catalogue))
    return Response({"modules": modules, "permissions": [{"code": p.code, "module": p.module, "action": p.action, "name": p.name} for p in catalogue], "roles": [{"id": r.id, "name": r.name, "code": r.code, "modules": {m: {p.action: p in r.permissions.all() for p in catalogue if p.module == m} for m in modules}} for r in roles]})


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "settings.edit", "POST": "settings.edit"})
def masters(request, organization_slug, master_type=None):
    access = _org_access(request, organization_slug, request.method == "POST")
    category_code = (master_type or "").replace("-", "_")
    project = None
    if request.headers.get("X-Project-ID"):
        from organizations.services import get_project_context
        project = get_project_context(request, access)
    query = MasterData.objects.filter(organization=access.organization, project=project)
    if master_type: query = query.filter(category__code=category_code)
    if request.method == "GET":
        if not access.is_platform and not has_permission(request.user, access.organization, "settings.edit"):
            query = query.filter(is_active=True)
        return Response(LegacyMasterDataSerializer(query, many=True).data)
    if not master_type: return Response({"master_type": "Use a controlled master type URL."}, status=400)
    category = get_object_or_404(MasterDataCategory, code=category_code)
    serializer = LegacyMasterDataSerializer(data=request.data); serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        item = serializer.save(organization=access.organization, project=project, category=category)
    return Response(LegacyMasterDataSerializer(item).data, status=201)


@crm_endpoint(["PATCH", "DELETE"], scope="organization", permissions={"PATCH": "settings.edit", "DELETE": "settings.edit"})
def master_detail(request, organization_slug, master_type, item_id):
    access = _org_access(request, organization_slug, True); item = get_object_or_404(MasterData, organization=access.organization, category__code=master_type.replace("-", "_"), pk=item_id)
    if request.method == "DELETE":
        if not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
        if item.is_system: return Response({"code": "system_item_cannot_be_deleted", "detail": "System master data can only be deactivated."}, status=409)
        item.delete(); return Response(status=204)
    serializer = LegacyMasterDataSerializer(item, data=request.data, partial=True); serializer.is_valid(raise_exception=True); item = serializer.save(); return Response(LegacyMasterDataSerializer(item).data)


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "settings.edit", "POST": "settings.edit"})
def integrations(request, organization_slug):
    access = _org_access(request, organization_slug, request.method == "POST")
    if request.method == "GET": return Response(IntegrationSerializer(IntegrationConfiguration.objects.filter(organization=access.organization), many=True).data)
    serializer = IntegrationSerializer(data=request.data); serializer.is_valid(raise_exception=True)
    secrets = serializer.validated_data.pop("secrets", None)
    if secrets is not None and not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    obj = serializer.save(organization=access.organization, encrypted_secrets=encrypt_secret(secrets) if secrets is not None else "", status=IntegrationConfiguration.Status.CONFIGURED)
    return Response(IntegrationSerializer(obj).data, status=201)


@crm_endpoint(["PATCH"], scope="organization", permissions={"PATCH": "settings.edit"})
def integration_detail(request, organization_slug, integration_id):
    access = _org_access(request, organization_slug, True); obj = get_object_or_404(IntegrationConfiguration, organization=access.organization, pk=integration_id)
    serializer = IntegrationSerializer(obj, data=request.data, partial=True); serializer.is_valid(raise_exception=True); secrets = serializer.validated_data.pop("secrets", None)
    critical = secrets is not None or ("enabled" in serializer.validated_data and not serializer.validated_data["enabled"] and obj.enabled)
    if critical and not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    if secrets is not None: serializer.validated_data["encrypted_secrets"] = encrypt_secret(secrets)
    obj = serializer.save(status=IntegrationConfiguration.Status.CONFIGURED if serializer.validated_data.get("enabled", obj.enabled) else IntegrationConfiguration.Status.DISABLED)
    return Response(IntegrationSerializer(obj).data)


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "settings.edit", "POST": "settings.edit"})
def system_parameters(request, organization_slug):
    access = _org_access(request, organization_slug, request.method == "POST")
    project = None
    if request.headers.get("X-Project-ID"):
        from organizations.services import get_project_context
        project = get_project_context(request, access)
    if request.method == "GET": return Response(LegacySystemParameterSerializer(SystemParameter.objects.filter(organization=access.organization, project=project), many=True).data)
    serializer = LegacySystemParameterSerializer(data=request.data); serializer.is_valid(raise_exception=True)
    if serializer.validated_data.get("is_critical") and not serializer.validated_data.pop("confirmation", False): return Response({"code": "confirmation_required"}, status=409)
    item = serializer.save(organization=access.organization, project=project); invalidate_system_parameter_cache(access.organization, item.parameter_key, project); return Response(LegacySystemParameterSerializer(item).data, status=201)


@crm_endpoint(["PATCH", "DELETE"], scope="organization", permissions={"PATCH": "settings.edit", "DELETE": "settings.edit"})
def system_parameter_detail(request, organization_slug, parameter_id):
    access = _org_access(request, organization_slug, True); item = get_object_or_404(SystemParameter, organization=access.organization, pk=parameter_id)
    if request.method == "DELETE":
        if item.is_critical and not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
        parameter_key, project = item.parameter_key, item.project
        item.delete(); invalidate_system_parameter_cache(access.organization, parameter_key, project); return Response(status=204)
    serializer = LegacySystemParameterSerializer(item, data=request.data, partial=True); serializer.is_valid(raise_exception=True)
    if item.is_critical and "value" in serializer.validated_data and not serializer.validated_data.pop("confirmation", False): return Response({"code": "confirmation_required"}, status=409)
    previous_key, previous_project = item.parameter_key, item.project
    item = serializer.save()
    invalidate_system_parameter_cache(access.organization, previous_key, previous_project)
    invalidate_system_parameter_cache(access.organization, item.parameter_key, item.project)
    return Response(LegacySystemParameterSerializer(item).data)


def _canonical_parameter_payload(item):
    definition = PARAMETER_REGISTRY[item.parameter_key]
    return {
        "id": item.id,
        "parameter_key": item.parameter_key,
        "parameter_name": item.parameter_name or definition.name,
        "value": item.value,
        "data_type": item.data_type,
        "description": item.description,
        "is_active": item.is_active,
        "is_critical": item.is_critical,
        "scope": definition.scope,
        "min": definition.min_value,
        "max": definition.max_value,
    }


@crm_endpoint(["GET"], scope="organization", permissions={"GET": "settings.view"})
def master_data_categories(request, organization_slug):
    return Response([
        {
            "id": category.id,
            "code": category.code,
            "name": category.name,
            "description": category.description,
            "is_system": category.is_system,
        }
        for category in MasterDataCategory.objects.all()
    ])


@crm_endpoint(["GET"], scope="project")
def master_data_list(request, organization_slug, category_code):
    category = get_object_or_404(MasterDataCategory, code=category_code)
    query = MasterData.objects.filter(
        organization=request.crm_access.organization,
        project=request.crm_project,
        category=category,
    ).order_by("sort_order", "name")
    if request.query_params.get("include_inactive") != "1" or not has_permission(
        request.user, request.crm_access.organization, "settings.view", project=request.crm_project
    ):
        query = query.filter(is_active=True)
    return Response(MasterDataSerializer(query, many=True).data)


@crm_endpoint(["POST"], scope="project", permissions={"POST": "settings.edit"})
def master_data_create(request, organization_slug):
    serializer = MasterDataSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            item = serializer.save(organization=request.crm_access.organization, project=request.crm_project)
    except IntegrityError:
        return Response({"detail": "A master-data key already exists in this scope."}, status=400)
    return Response(MasterDataSerializer(item).data, status=201)


@crm_endpoint(["PUT"], scope="project", permissions={"PUT": "settings.edit"})
def master_data_update(request, organization_slug, category_code, item_id):
    item = get_object_or_404(
        MasterData,
        organization=request.crm_access.organization,
        project=request.crm_project,
        category__code=category_code,
        pk=item_id,
    )
    serializer = MasterDataSerializer(item, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        item = serializer.save()
    return Response(MasterDataSerializer(item).data)


@crm_endpoint(["GET", "POST"], scope="organization", permissions={"GET": "settings.view", "POST": "settings.edit"})
def master_data_defaults_list(request, organization_slug, category_code=None):
    if request.method == "POST":
        serializer = MasterDataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                item = serializer.save(organization=request.crm_access.organization, project=None)
        except IntegrityError:
            return Response({"detail": "A master-data key already exists in this scope."}, status=400)
        return Response(MasterDataSerializer(item).data, status=201)
    query = MasterData.objects.filter(organization=request.crm_access.organization, project__isnull=True).order_by("category__code", "sort_order", "name")
    if category_code:
        query = query.filter(category__code=category_code)
    return Response(MasterDataSerializer(query, many=True).data)


@crm_endpoint(["POST"], scope="organization", permissions={"POST": "settings.edit"})
def master_data_defaults_create(request, organization_slug):
    serializer = MasterDataSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            item = serializer.save(organization=request.crm_access.organization, project=None)
    except IntegrityError:
        return Response({"detail": "A master-data key already exists in this scope."}, status=400)
    return Response(MasterDataSerializer(item).data, status=201)


@crm_endpoint(["PUT"], scope="organization", permissions={"PUT": "settings.edit"})
def master_data_defaults_update(request, organization_slug, item_id):
    item = get_object_or_404(MasterData, organization=request.crm_access.organization, project__isnull=True, pk=item_id)
    serializer = MasterDataSerializer(item, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        item = serializer.save()
    return Response(MasterDataSerializer(item).data)


@crm_endpoint(["GET", "PUT"], scope="project", permissions={"GET": "settings.view", "PUT": "settings.edit"})
def canonical_system_parameters(request, organization_slug):
    if request.method == "PUT":
        return canonical_system_parameter_update(request, organization_slug)
    ensure_project_parameter_defaults(request.crm_project)
    organization = request.crm_access.organization
    rows = list(SystemParameter.objects.filter(organization=organization, project=request.crm_project, is_active=True))
    rows.extend(SystemParameter.objects.filter(organization=organization, project__isnull=True, is_active=True, parameter_key="auto_logout_minutes"))
    return Response([_canonical_parameter_payload(item) for item in rows])


def canonical_system_parameter_update(request, organization_slug):
    organization = request.crm_access.organization
    key = request.data.get("parameter_key")
    value = request.data.get("value")
    try:
        definition = parameter_definition(key)
        value = validate_parameter_value(key, value)
    except (UnknownSystemParameter, TypeError, DrfValidationError):
        return Response({"parameter_key": "Unknown system parameter."}, status=400)
    if definition.scope == "organization":
        return Response({"parameter_key": "Organization-scoped parameters must use the defaults endpoint."}, status=400)
    if definition.data_type == SystemParameter.DataType.DECIMAL:
        value = float(value)
    item = get_object_or_404(SystemParameter, organization=organization, project=request.crm_project, parameter_key=key)
    if item.is_critical and not request.data.get("confirmation"):
        return Response({"code": "confirmation_required"}, status=409)
    item.value = value
    item.save(update_fields=["value", "updated_at"])
    invalidate_system_parameter_cache(organization, key, request.crm_project)
    return Response(_canonical_parameter_payload(item))


@crm_endpoint(["GET", "PUT"], scope="organization", permissions={"GET": "settings.view", "PUT": "settings.edit"})
def canonical_system_parameter_defaults(request, organization_slug):
    if request.method == "PUT":
        return canonical_system_parameter_default_update(request, organization_slug)
    ensure_organization_parameter_defaults(request.crm_access.organization)
    rows = SystemParameter.objects.filter(organization=request.crm_access.organization, project__isnull=True, is_active=True)
    return Response([_canonical_parameter_payload(item) for item in rows])


def canonical_system_parameter_default_update(request, organization_slug):
    organization = request.crm_access.organization
    key = request.data.get("parameter_key")
    try:
        definition = parameter_definition(key)
        value = validate_parameter_value(key, request.data.get("value"))
    except (UnknownSystemParameter, TypeError, DrfValidationError):
        return Response({"parameter_key": "Unknown system parameter."}, status=400)
    if definition.scope != "organization":
        return Response({"parameter_key": "This parameter is project-scoped."}, status=400)
    if definition.data_type == SystemParameter.DataType.DECIMAL:
        value = float(value)
    ensure_organization_parameter_defaults(organization)
    item = get_object_or_404(SystemParameter, organization=organization, project__isnull=True, parameter_key=key)
    if item.is_critical and not request.data.get("confirmation"):
        return Response({"code": "confirmation_required"}, status=409)
    item.value = value
    item.save(update_fields=["value", "updated_at"])
    invalidate_system_parameter_cache(organization, key)
    return Response(_canonical_parameter_payload(item))


@crm_endpoint(["GET"], scope="user")
def audit_logs(request):
    require_developer_audit_access(request.user); query = AuditLog.objects.select_related("organization", "project", "user")
    project_id = request.headers.get("X-Project-ID")
    if project_id:
        query = query.filter(project_id=project_id)
    else:
        query = query.filter(project__isnull=True)
    for key, lookup in (("user", "user_id"), ("organization", "organization_id"), ("module", "module"), ("action", "action")):
        if value := request.query_params.get(key): query = query.filter(**{lookup: value})
    if value := request.query_params.get("search"):
        query = query.filter(
            Q(module__icontains=value) |
            Q(action__icontains=value) |
            Q(ip_address__icontains=value) |
            Q(user__email__icontains=value)
        )
    if value := request.query_params.get("date_from"): query = query.filter(created_at__date__gte=value)
    if value := request.query_params.get("date_to"): query = query.filter(created_at__date__lte=value)
    return _page(query, request, AuditLogSerializer)


@crm_endpoint(["GET"], scope="organization")
def organization_audit_logs(request, organization_slug):
    require_developer_audit_access(request.user)
    access = get_organization_access(request.user, organization_slug)
    query = AuditLog.objects.select_related("organization", "project", "user").filter(organization=access.organization)
    if value := request.headers.get("X-Project-ID"):
        project = Project.objects.filter(pk=value, organization=access.organization).first()
        if project is None:
            return Response({"project": "Project not found."}, status=404)
        query = query.filter(project=project)
    else:
        query = query.filter(project__isnull=True)
    for key, lookup in (("user", "user_id"), ("module", "module"), ("action", "action")):
        if value := request.query_params.get(key): query = query.filter(**{lookup: value})
    if value := request.query_params.get("search"):
        query = query.filter(Q(module__icontains=value) | Q(action__icontains=value) | Q(ip_address__icontains=value) | Q(user__email__icontains=value))
    if value := request.query_params.get("date_from"): query = query.filter(created_at__date__gte=value)
    if value := request.query_params.get("date_to"): query = query.filter(created_at__date__lte=value)
    return _page(query, request, AuditLogSerializer)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def backups(request):
    require_platform_settings(request.user)
    if request.method == "GET": return _page(BackupRecord.objects.select_related("initiated_by"), request, BackupRecordSerializer)
    if not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    # No server-controlled backup backend is configured in this deployment.
    record = BackupRecord.objects.create(status=BackupRecord.Status.UNSUPPORTED, initiated_by=request.user, error_message_safe="No database backup backend is configured.", completed_at=timezone.now())
    log_audit(request=request, module="operations", action="backup_failed", details={"status": "unsupported"}, target=record)
    return Response(BackupRecordSerializer(record).data, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def maintenance(request):
    require_platform_settings(request.user)
    if not request.data.get("confirmation"): return Response({"code": "confirmation_required"}, status=409)
    operation = request.data.get("operation")
    if operation == "clear_cache": result = clear_system_cache()
    elif operation == "rebuild_search_index": result = rebuild_search_index()
    else: return Response({"operation": "Use clear_cache or rebuild_search_index."}, status=400)
    log_audit(request=request, module="operations", action="maintenance_completed" if result == "completed" else "maintenance_failed", details={"operation": operation, "status": result})
    return Response({"operation": operation, "status": result})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def health(request):
    require_platform_settings(request.user)
    result = health_check()
    if request.method == "POST": log_audit(request=request, module="operations", action="health_check", details={"status": result["status"]})
    return Response(result)
