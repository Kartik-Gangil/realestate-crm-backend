from django.test import TestCase

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs


class SharedTestFactoryTests(TestCase):
    def test_factories_create_system_roles_and_project_assignments(self):
        organization = make_organization("factory-org")
        project = make_project(organization, "FACTORY")

        for role_code in ("admin", "manager", "telecaller"):
            membership = make_member(organization, role=role_code, projects=[project])
            self.assertEqual(membership.organization_role.code, role_code)
            self.assertEqual(membership.organization_role.is_system, role_code == "admin")
            assignment = membership.project_assignments.get(project=project)
            self.assertEqual(assignment.role.code, role_code)

    def test_factories_keep_organizations_and_projects_isolated(self):
        first = make_organization("factory-first")
        second = make_organization("factory-second")
        first_project = make_project(first, "FIRST")
        second_project = make_project(second, "SECOND")
        first_member = make_member(first, role="manager", projects=[first_project])
        second_member = make_member(second, role="manager", projects=[second_project])

        self.assertEqual(first_member.organization_id, first.id)
        self.assertEqual(second_member.organization_id, second.id)
        self.assertEqual(list(first_member.project_assignments.values_list("project_id", flat=True)), [first_project.id])
        self.assertEqual(list(second_member.project_assignments.values_list("project_id", flat=True)), [second_project.id])
        self.assertFalse(first_member.project_assignments.filter(project=second_project).exists())

    def test_project_request_helper_sends_header_per_request(self):
        organization = make_organization("factory-header")
        project = make_project(organization, "HEADER")

        self.assertEqual(project_request_kwargs(project), {"HTTP_X_PROJECT_ID": str(project.id)})
        self.assertEqual(
            project_request_kwargs(project, data={"example": True}),
            {"HTTP_X_PROJECT_ID": str(project.id), "data": {"example": True}},
        )
