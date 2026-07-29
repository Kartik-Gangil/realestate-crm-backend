from dataclasses import dataclass

from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Organization, OrganizationMembership, PlatformOrganizationAccess

PLATFORM_ADMIN_GROUP = "Platform Admin"


@dataclass(frozen=True)
class OrganizationAccess:
    organization: Organization
    membership: OrganizationMembership | None
    is_platform: bool

    @property
    def can_view_all_leads(self):
        return self.is_platform or self.membership.role in {OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.MANAGER}

    @property
    def can_manage_leads(self):
        return self.can_view_all_leads

    @property
    def can_manage_members(self):
        return self.is_platform or self.membership.role == OrganizationMembership.Role.ADMIN


def is_platform_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=PLATFORM_ADMIN_GROUP).exists())


def get_organization_access(user, slug):
    try:
        organization = Organization.objects.get(slug=slug, is_active=True)
    except Organization.DoesNotExist as error:
        raise NotFound("Organization not found.") from error
    if user.is_superuser:
        return OrganizationAccess(organization, None, True)
    if is_platform_admin(user) and PlatformOrganizationAccess.objects.filter(organization=organization, user=user).exists():
        return OrganizationAccess(organization, None, True)
    membership = OrganizationMembership.objects.filter(organization=organization, user=user, is_active=True).first()
    if membership:
        return OrganizationAccess(organization, membership, False)
    raise PermissionDenied("You do not have access to this organization.")