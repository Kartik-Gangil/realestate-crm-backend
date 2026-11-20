from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from inventory.models import Project
from expenses.models import ExpenseCategory
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission
from organizations import models as organization_models
from organizations.services import ensure_default_roles
from organizations.services import has_permission

from .models import MasterData, MasterDataCategory, SystemParameter
from . import services


class Phase2DynamicBindingTests(TestCase):
    """FR-P2-01/02/03/04 and DM-P2-02/03."""

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="settings-admin", email="settings-admin@example.test", password="Valid123!")
        self.manager = user_model.objects.create_user(username="settings-manager", email="settings-manager@example.test", password="Valid123!")
        self.organization = Organization.objects.create(name="Dynamic Org", slug="dynamic-org")
        roles = ensure_default_roles(self.organization)
        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role="admin", organization_role=roles["admin"]
        )
        self.manager_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.manager, role="manager", organization_role=roles["manager"]
        )
        self.client = APIClient()

    def test_system_parameter_is_typed_cached_and_invalidated(self):
        parameter = SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="site_visit_max_days_ahead",
            parameter_name="Site visit maximum days ahead",
            value=90,
            data_type=SystemParameter.DataType.INTEGER,
        )

        self.assertEqual(services.get_system_parameter(self.organization, parameter.parameter_key), 90)
        parameter.value = 120
        parameter.save(update_fields=["value"])
        self.assertEqual(services.get_system_parameter(self.organization, parameter.parameter_key), 90)

        services.invalidate_system_parameter_cache(self.organization, parameter.parameter_key)
        self.assertEqual(services.get_system_parameter(self.organization, parameter.parameter_key), 120)

    def test_project_parameter_overrides_organization_default(self):
        project = Project.objects.create(organization=self.organization, name="Project A", code="PA")
        SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="booking_hold_days",
            parameter_name="Booking hold days",
            value=7,
            data_type=SystemParameter.DataType.INTEGER,
        )
        parameter = SystemParameter.objects.get(organization=self.organization, project=project, parameter_key="booking_hold_days")
        parameter.value = 25
        parameter.save(update_fields=["value"])

        self.assertEqual(services.get_system_parameter(self.organization, "booking_hold_days"), 7)
        self.assertEqual(services.get_system_parameter(self.organization, "booking_hold_days", project=project), 25)

    def test_project_creation_copies_configuration_defaults(self):
        MasterData.objects.create(
            organization=self.organization,
            category=MasterDataCategory.objects.get(code="expense_category"),
            code="travel",
            name="Travel",
            is_system=True,
        )
        SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="booking_hold_days",
            parameter_name="Booking hold days",
            value=7,
            data_type=SystemParameter.DataType.INTEGER,
        )
        ExpenseCategory.objects.create(
            organization=self.organization,
            name="Travel default",
        )
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            "/api/organizations/dynamic-org/inventory/projects/",
            {"name": "Project B", "code": "PB"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        project = Project.objects.get(pk=response.data["id"])
        self.assertTrue(MasterData.objects.filter(project=project, code="travel").exists())
        self.assertTrue(SystemParameter.objects.filter(project=project, parameter_key="booking_hold_days").exists())
        self.assertTrue(ExpenseCategory.objects.filter(project=project, name="Travel default").exists())

    def test_project_category_reader_uses_only_the_project_copy_g1_item_4(self):
        project = Project.objects.create(organization=self.organization, name="Project C", code="PC")
        ExpenseCategory.objects.create(organization=self.organization, name="Organization default")
        ExpenseCategory.objects.create(organization=self.organization, project=project, name="Project copy")
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/categories/", HTTP_X_PROJECT_ID=str(project.pk))

        self.assertEqual(response.status_code, 200, response.data)
        names = [item["name"] for item in response.data["data"]]
        self.assertEqual(names, ["Project copy"])

    def test_non_admin_master_lookup_hides_inactive_items(self):
        category = MasterDataCategory.objects.get(code="expense_category")
        MasterData.objects.create(organization=self.organization, category=category, code="active", name="Active", is_active=True)
        MasterData.objects.create(organization=self.organization, category=category, code="inactive", name="Inactive", is_active=False)
        self.client.force_authenticate(self.manager)

        response = self.client.get("/api/organizations/dynamic-org/settings/masters/expense-category/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([item["code"] for item in response.data], ["active"])

    def test_system_master_data_cannot_be_deleted(self):
        item = MasterData.objects.create(
            organization=self.organization,
            category=MasterDataCategory.objects.get(code="plot_status"),
            code="available",
            name="Available",
            is_system=True,
        )
        self.client.force_authenticate(self.admin)

        response = self.client.delete(
            f"/api/organizations/dynamic-org/settings/masters/plot-status/{item.id}/",
            {"confirmation": True},
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(MasterData.objects.filter(pk=item.id).exists())


class Phase3PermissionVerificationTests(TestCase):
    """FR-P3-03/FR-P3-06/EC-P3-01/NFR-P3-03."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="rbac-user", email="rbac-user@example.test", password="Valid123!")
        self.organization = Organization.objects.create(name="RBAC Org", slug="rbac-org")
        role = OrganizationRole.objects.create(organization=self.organization, name="Settings Viewer", code="settings-viewer")
        view_permission = Permission.objects.get_or_create(module="settings", action="view", defaults={"name": "View settings"})[0]
        role.permissions.add(view_permission)
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, role="manager", organization_role=role
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_revoking_permission_blocks_next_request(self):
        self.assertEqual(self.client.get("/api/organizations/rbac-org/settings/general/").status_code, 200)
        self.membership.organization_role.permissions.clear()

        response = self.client.get("/api/organizations/rbac-org/settings/general/")

        self.assertEqual(response.status_code, 403, response.data)

    def test_project_roles_are_bound_to_the_requested_project(self):
        project_a = Project.objects.create(organization=self.organization, name="Project A", code="A")
        project_b = Project.objects.create(organization=self.organization, name="Project B", code="B")
        project_role = OrganizationRole.objects.create(organization=self.organization, name="Project Viewer", code="project-viewer")
        permission = Permission.objects.get_or_create(module="leads", action="view", defaults={"name": "View leads"})[0]
        project_role.permissions.add(permission)
        organization_models.ProjectAssignment.objects.create(
            membership=self.membership,
            project=project_a,
            role=project_role,
        )

        self.assertTrue(has_permission(self.user, self.organization, "leads.view", project=project_a))
        self.assertFalse(has_permission(self.user, self.organization, "leads.view", project=project_b))

        project_role.permissions.clear()
        self.assertFalse(has_permission(self.user, self.organization, "leads.view", project=project_a))

    def test_tab_permissions_bind_to_the_active_project_role(self):
        project = Project.objects.create(organization=self.organization, name="Project Tabs", code="TABS")
        project_role = OrganizationRole.objects.create(organization=self.organization, name="Lead Viewer", code="lead-viewer")
        permission = Permission.objects.get_or_create(module="leads", action="view", defaults={"name": "View leads"})[0]
        project_role.permissions.add(permission)
        organization_models.ProjectAssignment.objects.create(membership=self.membership, project=project, role=project_role)

        response = self.client.get(
            "/api/organizations/rbac-org/my-tab-permissions/",
            HTTP_X_PROJECT_ID=str(project.id),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("leads.view", response.data["permissions"])
        self.assertNotIn("settings.view", response.data["permissions"])
        self.assertIn("leads", response.data["effective_tab_permissions"])
