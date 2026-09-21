import re

from django.http import JsonResponse
from django.urls import Resolver404, resolve
from django.utils import timezone

from .models import Organization, Project
from .project_scope import reset_current_project, set_current_project


VERSIONED_ORGANIZATION_API = re.compile(
    r"^/api/v1/organizations/(?P<organization_slug>[-a-zA-Z0-9_]+)/"
)


class ProjectContextMiddleware:
    """FR-P0-02: resolve project context before versioned tenant controllers run."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = VERSIONED_ORGANIZATION_API.match(request.path_info)
        if match is None:
            return self.get_response(request)

        try:
            resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)

        project_code = request.headers.get("X-Project-ID", "").strip()
        if not project_code:
            has_authentication = bool(request.headers.get("Authorization")) or bool(
                getattr(request, "user", None) and request.user.is_authenticated
            )
            if not has_authentication:
                return self.get_response(request)
            return self._error(
                "project_context_required",
                "Select an active project before continuing.",
            )

        project = Project.objects.select_related("organization").filter(
            code__iexact=project_code,
            status=Project.Status.ACTIVE,
            organization__slug=match.group("organization_slug"),
            organization__status=Organization.Status.ACTIVE,
        ).first()
        if project is None:
            return self._error(
                "invalid_project_context",
                "The selected project is no longer valid. Select a project again.",
            )

        request.project = project
        request.project_id = project.pk
        token = set_current_project(project.pk)
        try:
            return self.get_response(request)
        finally:
            reset_current_project(token)

    @staticmethod
    def _error(code, message):
        return JsonResponse(
            {
                "success": False,
                "data": None,
                "error": {"code": code, "message": message},
                "meta": {
                    "timestamp": timezone.now().isoformat(),
                    "project_id": None,
                },
            },
            status=409,
        )
