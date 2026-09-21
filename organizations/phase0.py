from django.utils import timezone
from django.db.models import F, Q
from rest_framework import status
from rest_framework.response import Response

from .models import Organization, OrganizationMembership, Project


def api_success(data, *, project=None, response_status=status.HTTP_200_OK):
    return Response(
        {
            "success": True,
            "data": data,
            "error": None,
            "meta": {
                "timestamp": timezone.now().isoformat(),
                "project_id": project.code if project else None,
            },
        },
        status=response_status,
    )


def api_error(code, message, *, project=None, response_status=status.HTTP_400_BAD_REQUEST):
    return Response(
        {
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
            "meta": {
                "timestamp": timezone.now().isoformat(),
                "project_id": project.code if project else None,
            },
        },
        status=response_status,
    )


def accessible_organizations(user):
    if user.is_superuser:
        return Organization.objects.filter(status=Organization.Status.ACTIVE)
    return Organization.objects.filter(
        memberships__user=user,
        memberships__is_active=True,
        status=Organization.Status.ACTIVE,
    ).distinct()


def accessible_projects(user, *, include_inactive=False):
    projects = Project.objects.select_related("organization")
    if not user.is_superuser:
        projects = projects.filter(
            organization__memberships__user=user,
            organization__memberships__is_active=True,
        ).filter(
            Q(organization__memberships__projects__isnull=True)
            | Q(organization__memberships__projects=F("pk"))
        )
    if not include_inactive:
        projects = projects.filter(
            status=Project.Status.ACTIVE,
            organization__status=Organization.Status.ACTIVE,
        )
    return projects.distinct()


def can_manage_projects(user, organization):
    if user.is_superuser:
        return True
    return OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        role=OrganizationMembership.Role.ADMIN,
        is_active=True,
    ).exists()


def resolve_project_context(request, *, expected_project=None):
    project_code = request.headers.get("X-Project-ID", "").strip()
    if not project_code:
        return None, api_error(
            "project_context_required",
            "Select an active project before continuing.",
            response_status=status.HTTP_409_CONFLICT,
        )
    project = accessible_projects(request.user).filter(code__iexact=project_code).first()
    if project is None or (expected_project is not None and project.pk != expected_project.pk):
        return None, api_error(
            "invalid_project_context",
            "The selected project is no longer valid. Select a project again.",
            response_status=status.HTTP_409_CONFLICT,
        )
    request.project = project
    return project, None
