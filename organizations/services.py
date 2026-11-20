from dataclasses import dataclass

from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from users.security import is_developer

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, PlatformOrganizationAccess, ProjectAssignment, TAB_PERMISSIONS

PLATFORM_ADMIN_GROUP = "Platform Admin"

# Navigation is a frontend convenience, but it must be derived from the same
# permission catalogue that protects backend actions.
TAB_PERMISSION_REQUIREMENTS = {
    "dashboard": ("dashboard.view",),
    "leads": ("leads.view",),
    "assigned_leads": ("assigned_leads.view", "leads.view"),
    "follow_ups": ("leads.view", "follow_ups.view", "telecalling.view"),
    "telecalling": ("telecalling.view",),
    "members": ("employees.view",),
    "site-visits": ("site_visits.view",),
    "plots": ("plots.view",),
    "payments": ("payments.view",),
    "registry": ("registry.view",),
    "loans": ("loans.view",),
    "employees": ("employees.view",),
    "documents": ("documents.view",),
    "expenses": ("expenses.view",),
    "communications": ("communication.view", "communications.view"),
    "settings": ("settings.view",),
}

ORGANIZATION_SCOPE_TABS = frozenset({"members", "employees", "settings"})


@dataclass
class OrganizationAccess:
    organization: Organization
    membership: OrganizationMembership | None
    is_platform: bool
    project: object | None = None

    @property
    def can_view_all_leads(self):
        return self.is_platform or (self.membership and self.membership.access_scope == OrganizationMembership.AccessScope.ALL) or any(
            has_permission(self.membership.user, self.organization, code, project=self.project)
            for code in ("leads.view_team", "leads.team_view", "leads.view_all")
        )

    @property
    def can_manage_leads(self):
        return self.can_view_all_leads

    @property
    def can_manage_members(self):
        return self.is_platform or has_permission(self.membership.user, self.organization, "employees.edit")


def is_platform_admin(user):
    return user.is_authenticated and (is_developer(user) or user.is_superuser or user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists())


def account_level(user, organization=None):
    """Developer 4, Super Admin 3, Organization Admin 2, all other users 1."""
    if is_developer(user):
        return 4
    if user.is_superuser or user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists():
        return 3
    if organization is not None:
        membership = OrganizationMembership.objects.filter(
            organization=organization, user=user, is_active=True
        ).select_related("organization_role").first()
        if is_organization_admin(membership):
            return 2
    return 1


def can_manage_account(actor, target, organization=None):
    return account_level(actor, organization) >= account_level(target, organization)


def can_access_platform_settings(user):
    """The single authorization decision for application-wide Settings APIs."""
    return is_platform_admin(user)


def membership_role_code(membership):
    return membership.organization_role.code if membership and membership.organization_role_id else (membership.role if membership else None)


def is_organization_admin(membership):
    """Return whether a membership has organization-wide administrator access."""
    if not membership or not membership.is_active:
        return False
    role = membership.organization_role
    if role and role.is_system and role.code == "admin":
        return True
    if role and role.permissions.filter(module="settings", action="edit").exists():
        return True
    return False


def ensure_default_roles(organization):
    """Idempotently provision canonical roles for newly created tenants."""
    roles = {}
    created = {}
    for code, name in (
        ("admin", "Organization admin"),
        ("manager", "Manager"),
        ("telecaller", "Telecaller"),
        ("site-visit-executive", "Site Visit Executive"),
        ("hr-admin", "HR Admin"),
        ("accounts", "Accounts"),
    ):
        roles[code], created[code] = OrganizationRole.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={"name": name, "is_system": code == "admin"},
        )
    demoted = list(OrganizationRole.objects.filter(organization=organization, is_system=True).exclude(pk=roles["admin"].pk))
    OrganizationRole.objects.filter(pk__in=[role.pk for role in demoted]).update(is_system=False)
    if demoted:
        from system_settings.audit import log_bulk_audit
        log_bulk_audit(module="roles", action="bulk_update", instances=demoted, organization=organization,
                       changed_values={"is_system": False})
    if not roles["admin"].is_system:
        roles["admin"].is_system = True
        roles["admin"].save(update_fields=["is_system", "updated_at"])
    for code in ("manager", "telecaller"):
        if roles[code].is_system:
            roles[code].is_system = False
            roles[code].save(update_fields=["is_system", "updated_at"])
    roles["admin"].permissions.set(Permission.objects.all())
    if created["manager"]:
        manager_permissions = list(
            Permission.objects.filter(
                module__in=["dashboard", "leads", "customers", "plots", "documents", "employees", "attendance", "leave"]
            ).exclude(action__in=["delete", "export"])
        )
        manager_permissions.extend(Permission.objects.filter(module="settings", action="view"))
        manager_permissions.extend(
            Permission.objects.filter(
                module="expenses",
                action__in=["view", "view_team", "approve", "reject", "mark_paid", "process_payment"],
            )
        )
        # Keep newly provisioned manager roles aligned with the payment and
        # registry permissions granted by the payment/registry migration.
        manager_permissions.extend(
            Permission.objects.filter(
                module="payments", action__in=["view", "add", "edit", "receipt"]
            )
        )
        manager_permissions.extend(
            Permission.objects.filter(
                module="registry", action__in=["view", "add", "edit", "status"]
            )
        )
        manager_permissions.extend(
            Permission.objects.filter(
                module__in=["leads", "plots", "documents", "site_visits", "telecalling", "employees"],
                action="view_team",
            )
        )
        manager_permissions.extend(Permission.objects.filter(module="plots", action__in=["hold", "book"]))
        roles["manager"].permissions.set(manager_permissions)
    if created["telecaller"]:
        telecaller_permissions = list(
            Permission.objects.filter(
                module__in=["dashboard", "customers", "follow_ups", "telecalling"],
                action__in=["view", "add", "edit"],
            )
        )
        telecaller_permissions.extend(Permission.objects.filter(module="leads", action="add"))
        telecaller_permissions.extend(Permission.objects.filter(module="employees", action="view"))
        telecaller_permissions.extend(Permission.objects.filter(module="plots", action__in=["view", "view_team", "book"]))
        roles["telecaller"].permissions.set(telecaller_permissions)
    if created["site-visit-executive"]:
        site_visit_executive_permissions = []
        for module, actions in (
            ("site_visits", ("view", "add", "edit")),
            ("plots", ("view", "hold", "book")),
            ("leads", ("view",)),
        ):
            site_visit_executive_permissions.extend(
                Permission.objects.filter(module=module, action__in=actions)
            )
        roles["site-visit-executive"].permissions.set(site_visit_executive_permissions)
    if created["hr-admin"]:
        hr_admin_permissions = list(
            Permission.objects.filter(
                module__in=["dashboard", "employees", "attendance", "leave"],
                action__in=["view", "view_team", "add", "edit", "manage", "approve", "view_compensation"],
            )
        )
        roles["hr-admin"].permissions.set(hr_admin_permissions)
    if created["accounts"]:
        accounts_permissions = list(
            Permission.objects.filter(module="expenses", action__in=["view", "view_team", "process_reimbursement", "reimburse"])
        )
        roles["accounts"].permissions.set(accounts_permissions)
    return roles


def has_permission(user, organization, permission_code, *, project=None):
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
    if is_organization_admin(membership):
        return True
    role = membership.organization_role
    if project is not None:
        assignment = ProjectAssignment.objects.filter(
            membership=membership, project=project
        ).select_related("role").first()
        if assignment is None:
            return False
        role = assignment.role
    if role:
        return role.permissions.filter(
            module=permission_code.split(".", 1)[0],
            action=permission_code.split(".", 1)[1] if "." in permission_code else "",
        ).exists()
    return False


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
        has_permission(access.membership.user, access.organization, permission, project=getattr(access, "project", None))
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


def membership_permission_codes(membership, *, project=None):
    """Return the canonical role permission codes for an active membership."""
    if not membership or not membership.is_active:
        return []
    if is_organization_admin(membership):
        return list(Permission.objects.values_list("module", "action"))
    role = membership.organization_role
    if project is not None:
        assignment = ProjectAssignment.objects.filter(membership=membership, project=project).select_related("role").first()
        if assignment is None:
            return []
        role = assignment.role
    if role:
        return list(role.permissions.values_list("module", "action"))
    return []


def effective_tab_permissions(membership, *, is_platform=False, project=None):
    """Return tabs allowed by the membership's role permissions."""
    if is_platform:
        return list(TAB_PERMISSIONS)
    permission_codes = {f"{module}.{action}" for module, action in membership_permission_codes(membership, project=project)}
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
    if (
        not access.is_platform
        and not is_organization_admin(access.membership)
        and not ProjectAssignment.objects.filter(membership=access.membership, project=project).exists()
    ):
        raise PermissionDenied("You are not assigned to this project.")
    access.project = project
    underlying_request = getattr(request, "_request", request)
    underlying_request._validated_project_id = project.pk
    request._validated_project_id = project.pk
    return project
