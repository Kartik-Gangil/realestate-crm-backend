from functools import wraps

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated

from organizations.services import get_organization_access, get_project_context, has_permission

from .audit import record_mutation


VALID_SCOPES = frozenset({"public", "user", "organization", "project"})
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def public_endpoint(view):
    """Mark a plain Django health/probe view as intentionally public."""
    view.public_endpoint = True
    return view


def crm_endpoint(methods, *, scope="user", permissions=None):
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unsupported CRM endpoint scope: {scope}")
    methods = tuple(methods)
    permissions = dict(permissions or {})

    def decorator(view):
        @api_view(methods)
        @permission_classes([AllowAny] if scope == "public" else [IsAuthenticated])
        @wraps(view)
        def endpoint(request, *args, **kwargs):
            if scope != "public" and not request.user.is_authenticated:
                raise NotAuthenticated()

            access = None
            project = None
            if scope in {"organization", "project"}:
                slug = kwargs.get("organization_slug") or kwargs.get("slug")
                access = get_organization_access(request.user, slug)
                if scope == "project":
                    project = get_project_context(request, access)

            request.crm_access = access
            request.crm_project = project

            permission_code = permissions.get(request.method)
            if permission_code:
                if access is None or not has_permission(
                    request.user,
                    access.organization,
                    permission_code,
                    project=project,
                ):
                    raise PermissionDenied(f"Permission denied for {permission_code}.")

            response = view(request, *args, **kwargs)
            if request.method in MUTATION_METHODS and response.status_code < 400:
                record_mutation(request, response)
            return response

        endpoint.crm_endpoint_spec = {"scope": scope, "permissions": permissions, "methods": methods}
        return endpoint

    return decorator
