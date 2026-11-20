from rest_framework.exceptions import PermissionDenied
from organizations.services import has_permission


def require_document_view(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "documents.view", project=getattr(access, "project", None)):
        raise PermissionDenied("This role does not have permission to view documents or eKYC records.")


def require_document_export(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "documents.export", project=getattr(access, "project", None)):
        raise PermissionDenied("This role does not have permission to download customer documents.")


def require_employee_document_export(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "employees.export"):
        raise PermissionDenied("This role does not have permission to download employee documents.")


def require_document_management(access):
    if not access.is_platform and not has_permission(access.membership.user, access.organization, "documents.edit", project=getattr(access, "project", None)):
        raise PermissionDenied("Only organization admins, managers, and authorized platform users can manage document verification and configuration.")
