from dataclasses import dataclass

from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, PlatformOrganizationAccess, TAB_PERMISSIONS

PLATFORM_ADMIN_GROUP = "Platform Admin"

# Navigation is a frontend convenience, but it must be derived from the same
# permission catalogue that protects backend actions.
TAB_PERMISSION_REQUIREMENTS = {
    "dashboard": ("dashboard.view",),
    "leads": ("leads.view",),
    "assigned_leads": ("leads.view",),
    "follow_ups": ("leads.view",),
    "members": ("employees.view",),
}


@dataclass(frozen=True)
class OrganizationAccess:
    organization: Organization
    membership: OrganizationMembership | None
    is_platform: bool

    @property
    def can_view_all_leads(self):
        return self.is_platform or (
            membership_role_code(self.membership) in {
                OrganizationMembership.Role.ADMIN,
                OrganizationMembership.Role.MANAGER,
            }
            or has_permission(self.membership.user, self.organization, "leads.view_team")
        )

    @property
    def can_manage_leads(self):
        return self.can_view_all_leads

    @property
    def can_manage_members(self):
        return self.is_platform or has_permission(self.membership.user, self.organization, "employees.edit")


def is_platform_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists())


def can_access_platform_settings(user):
    """The single authorization decision for application-wide Settings APIs."""
    return is_platform_admin(user)


def membership_role_code(membership):
    return membership.organization_role.code if membership and membership.organization_role_id else (membership.role if membership else None)


def ensure_default_roles(organization):
    """Idempotently provision canonical roles for newly created tenants."""
    roles = {}
    for code, name in (("admin", "Organization admin"), ("manager", "Manager"), ("telecaller", "Telecaller")):
        roles[code], _ = OrganizationRole.objects.get_or_create(organization=organization, code=code, defaults={"name": name, "is_system": True})
    roles["admin"].permissions.set(Permission.objects.all())
    if not roles["manager"].permissions.exists():
        roles["manager"].permissions.set(Permission.objects.filter(module__in=["dashboard", "leads", "customers", "plots", "documents", "employees", "attendance", "leave"]).exclude(action__in=["delete", "export"]))
    if not roles["telecaller"].permissions.exists():
        roles["telecaller"].permissions.set(Permission.objects.filter(module__in=["dashboard", "leads", "customers", "documents"], action__in=["view", "add", "edit"]))
    expense_permissions = Permission.objects.filter(module="expenses", action__in=["view_own", "edit_own", "submit", "view_team", "approve"])
    roles["manager"].permissions.add(*expense_permissions)
    roles["telecaller"].permissions.add(*expense_permissions)
    return roles


def has_permission(user, organization, permission_code):
    """Resolve tenant RBAC from the canonical role relation.

    Superusers and explicitly authorized platform admins retain application-wide
    administration. Legacy fallback exists only for pre-migration deployments.
    """
    if is_platform_admin(user):
        return True
    membership = OrganizationMembership.objects.filter(
        organization=organization, user=user, is_active=True
    ).select_related("organization_role").first()
    if not membership:
        return False
    if membership.organization_role_id:
        return membership.organization_role.permissions.filter(
            module=permission_code.split(".", 1)[0],
            action=permission_code.split(".", 1)[1] if "." in permission_code else "",
        ).exists()
    # Compatibility for memberships created by older integrations (and for
    # deployments where the role-mapping migration has not yet linked every
    # membership). Keep the same baseline matrix as ensure_default_roles()
    # instead of treating every unlinked role as an organization admin.
    module, _, action = permission_code.partition(".")
    if membership.role == OrganizationMembership.Role.ADMIN:
        return True
    if membership.role == OrganizationMembership.Role.MANAGER:
        return (module in {"dashboard", "leads", "customers", "plots", "documents", "employees", "attendance", "leave"} and action not in {"delete", "export"}) or (module == "expenses" and action in {"view_own", "edit_own", "submit", "view_team", "approve"})
    if membership.role == OrganizationMembership.Role.TELECALLER:
        return (module in {"dashboard", "leads", "customers", "documents"} and action in {"view", "add", "edit"}) or (module == "expenses" and action in {"view_own", "edit_own", "submit"})
    return False


def membership_permission_codes(membership):
    """Return the canonical role permission codes for an active membership."""
    if not membership or not membership.is_active:
        return []
    if membership.organization_role_id:
        return list(membership.organization_role.permissions.values_list("module", "action"))
    # Match the compatibility matrix used by has_permission().
    if membership.role == OrganizationMembership.Role.ADMIN:
        return list(Permission.objects.values_list("module", "action"))
    if membership.role == OrganizationMembership.Role.MANAGER:
        return list(Permission.objects.filter(
            module__in=["dashboard", "leads", "customers", "plots", "documents", "employees", "attendance", "leave"],
        ).exclude(action__in=["delete", "export"]).values_list("module", "action")) + [("expenses", action) for action in ("view_own", "edit_own", "submit", "view_team", "approve")]
    if membership.role == OrganizationMembership.Role.TELECALLER:
        return list(Permission.objects.filter(
            module__in=["dashboard", "leads", "customers", "documents"],
            action__in=["view", "add", "edit"],
        ).values_list("module", "action")) + [("expenses", action) for action in ("view_own", "edit_own", "submit")]
    return []


def effective_tab_permissions(membership, *, is_platform=False):
    """Return tabs allowed by the membership's role permissions."""
    if is_platform:
        return list(TAB_PERMISSIONS)
    permission_codes = {f"{module}.{action}" for module, action in membership_permission_codes(membership)}
    role_tabs = [
        tab for tab in TAB_PERMISSIONS
        if any(code in permission_codes for code in TAB_PERMISSION_REQUIREMENTS[tab])
    ]
    return role_tabs


def get_organization_access(user, slug):
    try:
        organization = Organization.objects.get(slug=slug, is_active=True)
    except Organization.DoesNotExist as error:
        raise NotFound("Organization not found.") from error
    # Platform authorization is deliberately separate from tenant membership.
    # Group-backed platform admins and superusers may administer all tenants.
    if is_platform_admin(user):
        return OrganizationAccess(organization, None, True)
    membership = OrganizationMembership.objects.filter(organization=organization, user=user, is_active=True).first()
    if membership:
        return OrganizationAccess(organization, membership, False)
    raise PermissionDenied("You do not have access to this organization.")
