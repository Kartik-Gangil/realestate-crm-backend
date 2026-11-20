from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from rest_framework.exceptions import PermissionDenied

from inventory.models import Project

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, ProjectAssignment
from .services import get_organization_access, get_project_context, has_permission


class ProjectAssignmentTests(TestCase):
    """DM-P3-04, FR-P0-02, G-1 items 5-7, GNFR-06."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="assignment-user@example.test",
            email="assignment-user@example.test",
            password="password123",
        )
        self.organization = Organization.objects.create(name="Assignment Org", slug="assignment-org")
        self.other_organization = Organization.objects.create(name="Other Org", slug="other-assignment-org")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.role_a = OrganizationRole.objects.create(
            organization=self.organization, name="Role A", code="role-a"
        )
        self.role_b = OrganizationRole.objects.create(
            organization=self.organization, name="Role B", code="role-b"
        )
        self.foreign_role = OrganizationRole.objects.create(
            organization=self.other_organization, name="Foreign", code="foreign"
        )
        self.project_a = Project.objects.create(
            organization=self.organization, name="Project A", code="A"
        )
        self.project_b = Project.objects.create(
            organization=self.organization, name="Project B", code="B"
        )
        self.foreign_project = Project.objects.create(
            organization=self.other_organization, name="Foreign Project", code="FOREIGN"
        )

    def test_duplicate_assignment_and_cross_organization_values_are_rejected_dm_p3_04(self):
        ProjectAssignment.objects.create(
            membership=self.membership, project=self.project_a, role=self.role_a
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectAssignment.objects.create(
                    membership=self.membership, project=self.project_a, role=self.role_b
                )

        foreign_project_assignment = ProjectAssignment(
            membership=self.membership, project=self.foreign_project, role=self.role_a
        )
        with self.assertRaises(ValidationError):
            foreign_project_assignment.full_clean()

        foreign_role_assignment = ProjectAssignment(
            membership=self.membership, project=self.project_a, role=self.foreign_role
        )
        with self.assertRaises(ValidationError):
            foreign_role_assignment.full_clean()

    def test_project_context_does_not_create_from_legacy_membership_links_fr_p0_02_gnfr_06(self):
        self.project_a.assigned_memberships.add(self.membership)
        request = RequestFactory().get("/", HTTP_X_PROJECT_ID=str(self.project_a.pk))
        request.user = self.user
        access = get_organization_access(self.user, self.organization.slug)

        with self.assertRaises(PermissionDenied):
            get_project_context(request, access)
        self.assertFalse(
            ProjectAssignment.objects.filter(
                membership=self.membership, project=self.project_a
            ).exists()
        )

    def test_same_user_can_have_project_specific_roles_g1_items_5_7_gnfr_06(self):
        permission, _ = Permission.objects.get_or_create(
            module="leads", action="view", defaults={"name": "View leads"}
        )
        self.role_a.permissions.add(permission)
        ProjectAssignment.objects.create(
            membership=self.membership, project=self.project_a, role=self.role_a
        )
        ProjectAssignment.objects.create(
            membership=self.membership, project=self.project_b, role=self.role_b
        )

        self.assertTrue(
            has_permission(self.user, self.organization, "leads.view", project=self.project_a)
        )
        self.assertFalse(
            has_permission(self.user, self.organization, "leads.view", project=self.project_b)
        )
