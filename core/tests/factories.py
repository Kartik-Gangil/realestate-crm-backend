from uuid import uuid4

from django.contrib.auth import get_user_model

from inventory.models import Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, ProjectAssignment
from organizations.services import ensure_default_roles


_next_lead_phone = 0


def make_organization(slug):
    """Create an isolated organization fixture with a readable name."""
    return Organization.objects.create(name=slug.replace("-", " ").title(), slug=slug)


def make_project(organization, code):
    """Create a project belonging to the supplied organization."""
    return Project.objects.create(
        organization=organization,
        name=code.replace("-", " ").title(),
        code=code,
    )


def make_member(organization, role="admin", projects=None):
    """Create a user, canonical organization membership, and project assignments."""
    roles = ensure_default_roles(organization)
    if role not in roles:
        raise ValueError(f"Unsupported factory role: {role}")
    user_model = get_user_model()
    identifier = uuid4().hex[:12]
    user = user_model.objects.create_user(
        username=f"{role}-{organization.slug}-{identifier}",
        email=f"{role}-{organization.slug}-{identifier}@example.com",
        password="password123",
    )
    membership = OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=role,
        organization_role=roles[role],
    )
    for project in projects or []:
        if project.organization_id != organization.id:
            raise ValueError("Project must belong to the member organization")
        ProjectAssignment.objects.create(
            membership=membership,
            project=project,
            role=roles[role],
        )
    return membership


def make_lead(organization, project, *, first_name="Test Lead", phone=None, **kwargs):
    """Create a lead fixture with a valid, unique Indian phone by default."""
    global _next_lead_phone
    if phone is None:
        _next_lead_phone += 1
        phone = str(9000000000 + _next_lead_phone)
    return Lead.objects.create(
        organization=organization,
        project=project,
        first_name=first_name,
        phone=phone,
        **kwargs,
    )


def project_request_kwargs(project, **kwargs):
    """Return per-request kwargs carrying the active project header."""
    return {**kwargs, "HTTP_X_PROJECT_ID": str(project.id)}
