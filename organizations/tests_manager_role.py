import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project
from inventory.models import Project
from leads.models import Lead
from system_settings.models import AuditLog

from .models import OrganizationMembership, Permission, ProjectAssignment
from .services import ensure_default_roles, is_organization_admin


class ManagerNormalRoleTests(TestCase):
    """FR-P3-06, FR-P2-04, G-1 items 7 and 9, DM-P3-04."""

    def setUp(self):
        self.organization = make_organization("manager-normal-role")
        self.projects = [
            make_project(self.organization, "Manager One"),
            make_project(self.organization, "Manager Two"),
        ]
        self.roles = ensure_default_roles(self.organization)
        self.manager_role = self.roles["manager"]
        self.settings_edit = Permission.objects.get(module="settings", action="edit")
        self.membership = make_member(self.organization, role="manager")
        # Simulate the pre-fix state that exists in the database before the data migration.
        self.manager_role.permissions.add(self.settings_edit)
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)

    def run_manager_migration(self):
        migration = importlib.import_module("organizations.migrations.0023_manager_normal_role")
        migration.migrate_manager_roles(django_apps, None)

    def project_headers(self, project):
        return {"HTTP_X_PROJECT_ID": str(project.pk)}

    def test_ensure_default_roles_creates_manager_without_settings_edit(self):
        organization = make_organization("new-manager-template")
        roles = ensure_default_roles(organization)
        self.assertFalse(roles["manager"].permissions.filter(module="settings", action="edit").exists())

    def test_manager_is_not_an_organization_admin_after_migration(self):
        self.run_manager_migration()
        self.membership.refresh_from_db()
        self.assertFalse(is_organization_admin(self.membership))

    def test_manager_gets_403_on_settings_edit_route(self):
        self.run_manager_migration()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/master-data/defaults/",
            {"category": "lead_source", "key": "manager-attempt", "value": "Attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_no_assignment_manager_gets_every_project_and_loses_settings_edit(self):
        self.run_manager_migration()

        assignments = ProjectAssignment.objects.filter(membership=self.membership)
        self.assertEqual(assignments.count(), len(self.projects))
        self.assertEqual(
            set(assignments.values_list("project_id", flat=True)),
            set(Project.objects.filter(organization=self.organization).values_list("pk", flat=True)),
        )
        self.assertTrue(all(assignment.role_id == self.manager_role.pk for assignment in assignments))
        self.assertFalse(self.manager_role.permissions.filter(pk=self.settings_edit.pk).exists())

    def test_existing_assignments_are_kept_exactly(self):
        ProjectAssignment.objects.create(
            membership=self.membership,
            project=self.projects[0],
            role=self.manager_role,
        )
        self.run_manager_migration()

        self.assertEqual(
            list(
                ProjectAssignment.objects.filter(membership=self.membership)
                .order_by("project_id")
                .values_list("project_id", flat=True)
            ),
            [self.projects[0].pk],
        )

    def test_manager_can_open_each_assigned_project_but_not_an_unassigned_project(self):
        ProjectAssignment.objects.create(
            membership=self.membership,
            project=self.projects[0],
            role=self.manager_role,
        )
        self.run_manager_migration()
        self.client.force_authenticate(self.membership.user)

        assigned_response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            **self.project_headers(self.projects[0]),
        )
        unassigned_response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            **self.project_headers(self.projects[1]),
        )
        self.assertEqual(assigned_response.status_code, 200, assigned_response.data)
        self.assertEqual(unassigned_response.status_code, 403, unassigned_response.data)

    def test_manager_stays_within_manager_grid_inside_an_assigned_project(self):
        ProjectAssignment.objects.create(
            membership=self.membership,
            project=self.projects[0],
            role=self.manager_role,
        )
        self.run_manager_migration()

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/assigned/",
            **self.project_headers(self.projects[0]),
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_migration_audits_each_created_assignment_and_role_change(self):
        self.run_manager_migration()

        assignment_audits = AuditLog.objects.filter(
            route="command:migrate", action="project_assignment_created"
        )
        role_audits = AuditLog.objects.filter(
            route="command:migrate", action="manager_settings_edit_removed"
        )
        self.assertEqual(assignment_audits.count(), len(self.projects))
        self.assertEqual(role_audits.count(), 1)
        self.assertTrue(all(row.organization_id == self.organization.pk for row in assignment_audits))
        self.assertTrue(all(row.project_id in {project.pk for project in self.projects} for row in assignment_audits))
        self.assertTrue(all(row.user_id is None for row in assignment_audits | role_audits))


class TemplatePermissionPersistenceTests(TestCase):
    """FR-P3-06: Manager and Telecaller permissions are editable after creation."""

    def test_removed_template_permissions_survive_role_provisioning_during_employee_creation(self):
        organization = make_organization("template-permission-persistence")
        roles = ensure_default_roles(organization)
        admin = make_member(organization, role="admin")
        manager_permission = Permission.objects.get(module="leads", action="view_team")
        telecaller_permission = Permission.objects.get(module="dashboard", action="view")
        roles["manager"].permissions.remove(manager_permission)
        roles["telecaller"].permissions.remove(telecaller_permission)

        ensure_default_roles(organization)
        client = APIClient()
        client.force_authenticate(admin.user)
        response = client.post(
            f"/api/v1/organizations/{organization.slug}/users/",
            {
                "email": "new-employee@example.test",
                "temporary_password": "temporary-pass-123",
                "first_name": "New",
                "last_name": "Employee",
                "role": "telecaller",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(
            roles["manager"].permissions.filter(pk=manager_permission.pk).exists()
        )
        self.assertFalse(
            roles["telecaller"].permissions.filter(pk=telecaller_permission.pk).exists()
        )


class ManagerTeamViewTests(TestCase):
    """FR-P3-07, FR-P3-06, DM-P3-02: Manager team visibility follows the grid."""

    def setUp(self):
        self.organization = make_organization("manager-team-view")
        self.project = make_project(self.organization, "Team Project")
        self.roles = ensure_default_roles(self.organization)
        self.admin = make_member(self.organization, role="admin")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.teammate = make_member(self.organization, role="telecaller", projects=[self.project])
        self.manager_lead = make_lead(
            self.organization, self.project, first_name="Manager", assigned_membership=self.manager
        )
        self.teammate_lead = make_lead(
            self.organization, self.project, first_name="Teammate", assigned_membership=self.teammate
        )
        self.manager_client = APIClient()
        self.manager_client.force_authenticate(self.manager.user)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin.user)

    def leads_response(self, client):
        return client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

    def test_manager_with_leads_view_team_sees_team_leads_in_assigned_project(self):
        response = self.leads_response(self.manager_client)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {self.manager_lead.pk, self.teammate_lead.pk},
        )

    def test_removing_leads_view_team_limits_manager_to_owned_leads_on_next_request(self):
        team_view = Permission.objects.get(module="leads", action="view_team")
        permission_ids = list(
            self.roles["manager"].permissions.exclude(pk=team_view.pk).values_list("pk", flat=True)
        )
        response = self.admin_client.put(
            f"/api/organizations/{self.organization.slug}/roles/{self.roles['manager'].pk}/permissions/",
            {"permission_ids": permission_ids},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        response = self.leads_response(self.manager_client)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {item["id"] for item in response.data["results"]},
            {self.manager_lead.pk},
        )

    def test_view_team_scopes_match_g1_and_new_manager_keeps_all_six(self):
        expected_scopes = {
            "leads.view_team": "project",
            "plots.view_team": "project",
            "documents.view_team": "project",
            "site_visits.view_team": "project",
            "telecalling.view_team": "project",
            "employees.view_team": "organization",
        }
        self.assertEqual(
            {
                permission.code: permission.scope
                for permission in Permission.objects.filter(module__in=[
                    "leads", "plots", "documents", "site_visits", "telecalling", "employees"
                ], action="view_team")
            },
            expected_scopes,
        )
        new_organization = make_organization("new-manager-team-template")
        new_manager = ensure_default_roles(new_organization)["manager"]
        self.assertTrue(
            set(new_manager.permissions.filter(action="view_team").values_list("module", flat=True))
            >= set(module.split(".")[0] for module in expected_scopes)
        )
