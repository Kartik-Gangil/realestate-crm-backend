from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Organization, OrganizationMembership, Permission, PlatformOrganizationAccess, TAB_PERMISSIONS
from .serializers import AddMembershipSerializer, MembershipSerializer, OrganizationSerializer
from .services import (ORGANIZATION_SCOPE_TABS, PLATFORM_ADMIN_GROUP,
                       ensure_default_roles, get_organization_access,
                       effective_tab_permissions, get_project_context, is_organization_admin,
                       is_platform_admin, membership_permission_codes, is_developer,
                       can_manage_account)
from core.endpoint import crm_endpoint
from system_settings.audit import log_audit


@crm_endpoint(["GET", "POST"], scope="user")
def platform_organizations(request):
    if not is_platform_admin(request.user):
        raise PermissionDenied("Only platform admins and superadmins can manage organizations.")
    if request.method == "GET":
        organizations = Organization.objects.all() if (request.user.is_superuser or is_developer(request.user)) else Organization.objects.filter(platform_accesses__user=request.user)
        return Response(OrganizationSerializer(organizations, many=True).data)

    serializer = OrganizationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    admin_email = request.data.get("organization_admin_email")
    if not admin_email:
        return Response({"organization_admin_email": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    org_admin = get_object_or_404(get_user_model(), email__iexact=admin_email)
    with transaction.atomic():
        organization = serializer.save(created_by=request.user)
        ensure_default_roles(organization)
        OrganizationMembership.objects.create(organization=organization, user=org_admin, role=OrganizationMembership.Role.ADMIN)
        if not request.user.is_superuser and not is_developer(request.user):
            PlatformOrganizationAccess.objects.create(organization=organization, user=request.user, granted_by=request.user)
    return Response(OrganizationSerializer(organization).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def organization_members(request, slug):
    access = get_organization_access(request.user, slug)
    if request.method == "GET":
        return Response(MembershipSerializer(access.organization.memberships.select_related("user"), many=True).data)
    if not access.can_manage_members:
        raise PermissionDenied("Only organization admins can manage members.")
    serializer = AddMembershipSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if (
        serializer.validated_data["role"] == OrganizationMembership.Role.ADMIN
        and not access.is_platform
        and not is_organization_admin(access.membership)
    ):
        raise PermissionDenied("Only organization admins can assign the admin role.")
    user = serializer.user
    if not can_manage_account(request.user, user, access.organization):
        raise PermissionDenied({"code": "account_level_forbidden", "detail": "You cannot change an account above your level."})
    membership, created = OrganizationMembership.objects.update_or_create(
        organization=access.organization,
        user=user,
        defaults={"role": serializer.validated_data["role"], "is_active": True},
    )
    log_audit(request=request, organization=access.organization, module="users", action="role_change", details={"fields": ["role"]}, target=membership, payload_after={"fields": ["role"]})
    return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def platform_admins(request):
    if not request.user.is_superuser and not is_developer(request.user):
        raise PermissionDenied("Only platform superadmins can promote platform admins.")
    email = request.data.get("email")
    user = get_object_or_404(get_user_model(), email__iexact=email)
    group, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP)
    user.groups.add(group)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    log_audit(request=request, module="organizations", action="platform_admin_promoted", details={"fields": ["platform_admin"]}, target=user, payload_after={"fields": ["platform_admin"]})
    return Response({"id": user.id, "email": user.email, "is_platform_admin": True}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def platform_organization_access(request, slug):
    if not request.user.is_superuser and not is_developer(request.user):
        raise PermissionDenied("Only platform superadmins can grant platform organization access.")
    organization = get_object_or_404(Organization, slug=slug)
    user = get_object_or_404(get_user_model(), email__iexact=request.data.get("email"))
    if not is_platform_admin(user):
        return Response({"email": ["User must be a platform admin first."]}, status=status.HTTP_400_BAD_REQUEST)
    access, created = PlatformOrganizationAccess.objects.get_or_create(organization=organization, user=user, defaults={"granted_by": request.user})
    return Response({"organization": organization.slug, "email": user.email}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_tab_permissions(request, slug):
    access = get_organization_access(request.user, slug)
    project = get_project_context(request, access) if request.headers.get("X-Project-ID") else None
    organization_permission_codes = (
        [permission.code for permission in Permission.objects.all()]
        if access.is_platform
        else [f"{module}.{action}" for module, action in membership_permission_codes(access.membership)]
    )
    project_permission_codes = (
        organization_permission_codes
        if access.is_platform
        else [f"{module}.{action}" for module, action in membership_permission_codes(access.membership, project=project)]
        if project is not None
        else []
    )
    role = "platform_admin" if access.is_platform else access.membership.organization_role.code if access.membership.organization_role_id else access.membership.role
    if project is not None and not access.is_platform:
        assignment = access.membership.project_assignments.filter(project=project).select_related("role").first()
        role = assignment.role.code if assignment else role
    organization_tabs = effective_tab_permissions(access.membership, is_platform=access.is_platform)
    project_tabs = effective_tab_permissions(access.membership, is_platform=access.is_platform, project=project) if project is not None else []
    if project is None:
        effective_tabs = organization_tabs
    else:
        effective_tabs = [
            tab for tab in TAB_PERMISSIONS
            if (tab in ORGANIZATION_SCOPE_TABS and tab in organization_tabs)
            or (tab not in ORGANIZATION_SCOPE_TABS and tab in project_tabs)
        ]
    return Response({
        "organization": access.organization.slug,
        "role": role,
        "available_tabs": TAB_PERMISSIONS,
        "permissions": project_permission_codes if project is not None else organization_permission_codes,
        "organization_permissions": organization_permission_codes,
        "project_permissions": project_permission_codes,
        "selected_tab_permissions": effective_tabs,
        "role_allowed_tabs": effective_tabs,
        "effective_tab_permissions": effective_tabs,
    })
