from rest_framework.exceptions import PermissionDenied
from organizations.services import can_access_platform_settings, has_permission
from users.security import is_developer


def require_platform_settings(user):
    if not can_access_platform_settings(user): raise PermissionDenied("Platform Settings access is required.")


def require_developer_audit_access(user):
    if not is_developer(user): raise PermissionDenied("Developer audit access is required.")


def require_organization_settings(access, user, edit=False):
    if access.is_platform: return
    code = "settings.edit" if edit else "settings.view"
    if not has_permission(user, access.organization, code): raise PermissionDenied("This role does not have Settings permission.")
