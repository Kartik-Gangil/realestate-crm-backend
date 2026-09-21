from rest_framework.exceptions import PermissionDenied
from organizations.models import OrganizationMembership
from organizations.services import can_access_platform_settings, has_permission, membership_role_code


def require_platform_settings(user):
    if not can_access_platform_settings(user): raise PermissionDenied("Platform Settings access is required.")


def require_organization_settings(access, user, edit=False):
    if access.is_platform: return
    code = "settings.edit" if edit else "settings.view"
    if not has_permission(user, access.organization, code): raise PermissionDenied("This role does not have Settings permission.")


def require_phase2_configuration_admin(access):
    """FR-P2-04: generic permissions cannot elevate a tenant user to config admin."""
    if access.is_platform:
        return
    if membership_role_code(access.membership) != OrganizationMembership.Role.ADMIN:
        raise PermissionDenied("Only Super Admin or Admin may edit master data and system parameters.")
