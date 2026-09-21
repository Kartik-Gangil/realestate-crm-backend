from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Organization, OrganizationMembership, Permission, PlatformOrganizationAccess, Project, TAB_PERMISSIONS
from .phase0 import (accessible_organizations, accessible_projects, api_error, api_success,
                     can_manage_projects, resolve_project_context)
from .serializers import AddMembershipSerializer, MembershipSerializer, OrganizationSerializer, ProjectSerializer
from .services import (PLATFORM_ADMIN_GROUP,
                       ensure_default_roles, get_organization_access,
                       is_platform_admin, membership_permission_codes)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def platform_organizations(request):
    if not is_platform_admin(request.user):
        raise PermissionDenied("Only platform admins and superadmins can manage organizations.")
    if request.method == "GET":
        organizations = Organization.objects.all() if request.user.is_superuser else Organization.objects.filter(platform_accesses__user=request.user)
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
        if not request.user.is_superuser:
            PlatformOrganizationAccess.objects.create(organization=organization, user=request.user, granted_by=request.user)
    return Response(OrganizationSerializer(organization).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_list(request):
    """API-P0-01: organizations assigned to the authenticated user."""
    data = OrganizationSerializer(accessible_organizations(request.user), many=True).data
    return api_success(data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def project_list(request):
    """API-P0-02/API-P0-03: assigned project discovery and Admin-only creation."""
    if request.method == "GET":
        return api_success(ProjectSerializer(accessible_projects(request.user), many=True).data)

    serializer = ProjectSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    organization = serializer.validated_data["organization"]
    if not can_manage_projects(request.user, organization):
        raise PermissionDenied("Only Super Admin or Admin roles may create projects.")
    project = serializer.save()
    from system_settings.audit import log_audit
    serialized = ProjectSerializer(project).data
    log_audit(
        request=request,
        organization=organization,
        module="projects",
        action="create",
        details={"payload_before": None, "payload_after": serialized},
        target=project,
    )
    return api_success(serialized, project=project, response_status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def project_detail(request, project_id):
    project = accessible_projects(request.user, include_inactive=True).filter(pk=project_id).first()
    if project is None:
        return api_error(
            "project_not_found", "Project not found.", response_status=status.HTTP_404_NOT_FOUND
        )

    if request.method == "GET":
        context, error = resolve_project_context(request, expected_project=project)
        if error:
            return error
        return api_success(ProjectSerializer(project).data, project=context)

    context, error = resolve_project_context(request, expected_project=project)
    if error:
        return error
    if not can_manage_projects(request.user, project.organization):
        raise PermissionDenied("Only Super Admin or Admin roles may modify projects.")

    from system_settings.audit import log_audit
    before = ProjectSerializer(project).data
    if request.method == "PATCH":
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        after = ProjectSerializer(project).data
        log_audit(
            request=request, organization=project.organization, module="projects", action="update",
            details={"payload_before": before, "payload_after": after}, target=project,
        )
        return api_success(after, project=context)

    project.status = Project.Status.INACTIVE
    project.save(update_fields=["status", "updated_at"])
    after = ProjectSerializer(project).data
    log_audit(
        request=request, organization=project.organization, module="projects", action="delete",
        details={"payload_before": before, "payload_after": after}, target=project,
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


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
    user = serializer.validated_data["user"]
    membership, created = OrganizationMembership.objects.update_or_create(
        organization=access.organization,
        user=user,
        defaults={"role": serializer.validated_data["role"], "is_active": True},
    )
    return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def platform_admins(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Only platform superadmins can promote platform admins.")
    email = request.data.get("email")
    user = get_object_or_404(get_user_model(), email__iexact=email)
    group, _ = Group.objects.get_or_create(name=PLATFORM_ADMIN_GROUP)
    user.groups.add(group)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return Response({"id": user.id, "email": user.email, "is_platform_admin": True}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def platform_organization_access(request, slug):
    if not request.user.is_superuser:
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
    permission_codes = (
        [permission.code for permission in Permission.objects.all()]
        if access.is_platform
        else [f"{module}.{action}" for module, action in membership_permission_codes(access.membership)]
    )
    return Response({
        "organization": access.organization.slug,
        "role": "platform_admin" if access.is_platform else access.membership.organization_role.code if access.membership.organization_role_id else access.membership.role,
        "available_tabs": TAB_PERMISSIONS,
        "permissions": permission_codes,
    })
