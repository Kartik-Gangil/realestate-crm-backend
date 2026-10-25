from dataclasses import dataclass

from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, PlatformOrganizationAccess, TAB_PERMISSIONS

PLATFORM_ADMIN_GROUP = "Platform Admin"

# Navigation is a frontend convenience, but it must be derived from the same
# permission catalogue that protects backend actions.
TAB_PERMISSION_REQUIREMENTS = {
    "dashboard": ("dashboard.view",),
    "leads": ("leads.view",),
    "assigned_leads": ("leads.view",),
    "follow_ups": ("leads.view", "follow_ups.view", "telecalling.view"),
    "telecalling": ("telecalling.view",),
    "members": ("employees.view",),
}


@dataclass(frozen=True)
class OrganizationAccess:
    organization: Organization
    membership: OrganizationMembership | None
    is_platform: bool

    @property
    def can_view_all_leads(self):
        return self.is_platform or (has_permission(self.membership.user, self.organization, "leads.view") and membership_role_code(self.membership) != OrganizationMembership.Role.TELECALLER)

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
    roles["manager"].permissions.add(*Permission.objects.filter(module="settings", action="view"))
    telecaller_permissions = Permission.objects.filter(
        module__in=["dashboard", "customers", "follow_ups", "telecalling"],
        action__in=["view", "add", "edit"],
    )
    roles["telecaller"].permissions.remove(*Permission.objects.filter(module="documents"))
    if not roles["telecaller"].permissions.exists():
        roles["telecaller"].permissions.set(telecaller_permissions)
    else:
        roles["telecaller"].permissions.add(*telecaller_permissions)
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
    # Compatibility only until the data migration has run.
    return membership.role == OrganizationMembership.Role.ADMIN


def data_scope_membership_ids(access):
    """Return memberships visible under the selected organization data scope."""
    if access.is_platform or not access.membership:
        return None
    membership = access.membership
    if membership.access_scope == OrganizationMembership.AccessScope.ALL:
        return None
    if membership.access_scope == OrganizationMembership.AccessScope.OWN:
        return {membership.pk}

    ids = {membership.pk}
    if membership.access_scope == OrganizationMembership.AccessScope.DEPARTMENT:
        if membership.department_id:
            ids.update(
                OrganizationMembership.objects.filter(
                    organization=membership.organization,
                    department_id=membership.department_id,
                    is_active=True,
                ).values_list("id", flat=True)
            )
        return ids

    if membership.access_scope == OrganizationMembership.AccessScope.CUSTOM:
        ids.update(membership.custom_scope_memberships.filter(is_active=True).values_list("id", flat=True))
        ids.update(
            OrganizationMembership.objects.filter(
                organization=membership.organization,
                department__in=membership.custom_scope_departments.all(),
                is_active=True,
            ).values_list("id", flat=True)
        )
        return ids

    return ids


def data_scope_is_unrestricted(access, module=None):
    """Return whether a request may see all records in its current project."""
    if access.is_platform or not access.membership:
        return True
    if access.membership.access_scope == OrganizationMembership.AccessScope.ALL:
        return True
    if module and any(
        has_permission(access.membership.user, access.organization, permission)
        for permission in (f"{module}.view_team", f"{module}.team_view", f"{module}.view_all")
    ):
        return True
    return False


def apply_data_scope(queryset, access, *, module=None, membership_lookups=(), user_lookups=()):
    """Apply organization data scope to a queryset with explicit owner relations.

    GNFR-06/FR-P3-07: project records are visible only through their assigned
    membership or owner user unless the membership has unrestricted/team scope.
    """
    if data_scope_is_unrestricted(access, module):
        return queryset
    membership_ids = data_scope_membership_ids(access) or set()
    user_ids = set(
        OrganizationMembership.objects.filter(pk__in=membership_ids).values_list("user_id", flat=True)
    )
    predicates = [Q(**{f"{lookup}__in": membership_ids}) for lookup in membership_lookups]
    predicates.extend(Q(**{f"{lookup}__in": user_ids}) for lookup in user_lookups)
    if not predicates:
        return queryset.none()
    combined = predicates[0]
    for predicate in predicates[1:]:
        combined |= predicate
    return queryset.filter(combined).distinct()


def membership_permission_codes(membership):
    """Return the canonical role permission codes for an active membership."""
    if not membership or not membership.is_active:
        return []
    if membership.organization_role_id:
        return list(membership.organization_role.permissions.values_list("module", "action"))
    # Legacy fallback is deliberately narrow: only legacy organization admins
    # retain full access until their membership is linked to a canonical role.
    if membership.role == OrganizationMembership.Role.ADMIN:
        return list(Permission.objects.values_list("module", "action"))
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


def get_project_context(request, access):
    """Resolve and authorize the project carried by X-Project-ID."""
    from inventory.models import Project

    raw_project_id = request.headers.get("X-Project-ID")
    if not raw_project_id:
        raise ValidationError({"project": "X-Project-ID is required."})
    try:
        project_id = int(raw_project_id)
    except (TypeError, ValueError) as error:
        raise ValidationError({"project": "X-Project-ID must be a valid project id."}) from error
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise NotFound("Project not found.")
    if project.organization_id != access.organization.id:
        raise PermissionDenied("You do not have access to this project.")
    return project
