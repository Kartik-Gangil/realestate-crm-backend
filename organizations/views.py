from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Organization, OrganizationMembership, PlatformOrganizationAccess, TAB_PERMISSIONS
from .serializers import AddMembershipSerializer, MembershipSerializer, OrganizationSerializer, TabPermissionsSerializer
from .services import PLATFORM_ADMIN_GROUP, get_organization_access, is_platform_admin


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
        OrganizationMembership.objects.create(organization=organization, user=org_admin, role=OrganizationMembership.Role.ADMIN)
        if not request.user.is_superuser:
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
    user = serializer.user
    membership, created = OrganizationMembership.objects.update_or_create(
        organization=access.organization,
        user=user,
        defaults={"role": serializer.validated_data["role"], "is_active": True},
    )
    if "tab_permissions" in serializer.validated_data:
        membership.tab_permissions = serializer.validated_data["tab_permissions"]
        membership.save(update_fields=["tab_permissions"])
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
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def member_tab_permissions(request, slug, membership_id):
    access = get_organization_access(request.user, slug)
    if not access.can_manage_members:
        raise PermissionDenied("Only organization admins can manage tab permissions.")
    membership = get_object_or_404(access.organization.memberships.select_related("user"), pk=membership_id)
    if request.method == "GET":
        return Response({"available_tabs": TAB_PERMISSIONS, "member": MembershipSerializer(membership).data})
    serializer = TabPermissionsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    membership.tab_permissions = serializer.validated_data["tab_permissions"]
    membership.save(update_fields=["tab_permissions"])
    return Response(MembershipSerializer(membership).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_tab_permissions(request, slug):
    access = get_organization_access(request.user, slug)
    enabled_tabs = list(TAB_PERMISSIONS) if access.is_platform else access.membership.tab_permissions
    return Response({"organization": access.organization.slug, "available_tabs": TAB_PERMISSIONS, "tab_permissions": enabled_tabs})