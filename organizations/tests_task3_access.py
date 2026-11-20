from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from documents.models import DocumentCategory
from expenses.models import Expense, ExpenseCategory
from inventory.models import Block, Plot, Project
from leads.models import Lead

from .models import Organization, OrganizationMembership, OrganizationRole, Permission, ProjectAssignment
from .services import ensure_default_roles


class Task3AccessBase(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="Org X", slug="org-x")
        self.other_organization = Organization.objects.create(name="Org Y", slug="org-y")
        self.roles = ensure_default_roles(self.organization)
        self.other_roles = ensure_default_roles(self.other_organization)
        self.project_a = Project.objects.create(organization=self.organization, name="Project A", code="A")
        self.project_b = Project.objects.create(organization=self.organization, name="Project B", code="B")
        self.project_y = Project.objects.create(organization=self.other_organization, name="Project Y", code="Y")
        self.block_b = Block.objects.create(organization=self.organization, project=self.project_b, name="Block B", code="B")
        self.block_a = Block.objects.create(organization=self.organization, project=self.project_a, name="Block A", code="A")
        self.category_b = ExpenseCategory.objects.create(organization=self.organization, project=self.project_b, name="Travel")
        self.document_category = DocumentCategory.objects.create(organization=self.organization, name="Identity", code="identity")

        self.admin = user_model.objects.create_user(username="admin-x", email="admin-x@example.com", password="Password1!")
        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role="admin", organization_role=self.roles["admin"]
        )
        self.custom_admin = user_model.objects.create_user(username="settings-admin", email="settings-admin@example.com", password="Password1!")
        self.custom_admin_role = OrganizationRole.objects.create(organization=self.organization, name="Settings Admin", code="settings-admin")
        self.custom_admin_role.permissions.add(Permission.objects.get(module="settings", action="edit"))
        self.custom_admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.custom_admin, role="manager", organization_role=self.custom_admin_role
        )
        restricted_role = OrganizationRole.objects.create(organization=self.organization, name="Restricted", code="restricted")
        restricted_role.permissions.add(Permission.objects.get(module="leads", action="view"))
        self.restricted = user_model.objects.create_user(username="restricted", email="restricted@example.com", password="Password1!")
        self.restricted_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.restricted, role="manager", organization_role=restricted_role
        )
        self.manager = user_model.objects.create_user(username="manager-x", email="manager-x@example.com", password="Password1!")
        self.manager_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.manager, role="manager", organization_role=self.roles["manager"]
        )
        self.telecaller = user_model.objects.create_user(username="telecaller-x", email="telecaller-x@example.com", password="Password1!")
        self.telecaller_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.telecaller, role="telecaller", organization_role=self.roles["telecaller"]
        )
        self.platform_admin = user_model.objects.create_user(username="platform", email="platform@example.com", password="Password1!")
        self.platform_admin.groups.add(Group.objects.create(name="Platform Admin"))
        self.superuser = user_model.objects.create_superuser(username="superuser", email="superuser@example.com", password="Password1!")
        self.other_lead = Lead.objects.create(organization=self.organization, project=self.project_a, first_name="A", phone="9000000001")
        self.project_b_lead = Lead.objects.create(organization=self.organization, project=self.project_b, first_name="B", phone="9000000002")
        self.other_plot = Plot.objects.create(
            organization=self.organization, project=self.project_a, block=self.block_a,
            plot_number="A-1", size="100", total_price="1000",
        )
        self.target_user = user_model.objects.create_user(username="target", email="target@example.com", password="Password1!")

    def headers(self, project):
        return {"HTTP_X_PROJECT_ID": str(project.id)}

    def authenticate(self, user):
        self.client.force_authenticate(user)

    def plot_payload(self, number="B-1"):
        return {
            "block": self.block_b.id,
            "plot_number": number,
            "size": "100",
            "rate_per_sq_unit": "10",
            "total_price": "1000",
        }

    def create_plot_as(self, user, number="B-1"):
        self.authenticate(user)
        return self.client.post(
            f"/api/organizations/{self.organization.slug}/inventory/plots/",
            self.plot_payload(number), format="json", **self.headers(self.project_b),
        )


class Task3OrganizationAdminAccessTests(Task3AccessBase):
    def assert_project_operations_are_allowed(self, user):
        self.authenticate(user)
        leads = self.client.get(f"/api/organizations/{self.organization.slug}/leads/", **self.headers(self.project_b))
        self.assertEqual(leads.status_code, 200, leads.data)

        plot = self.create_plot_as(user, number=f"B-{user.id}")
        self.assertEqual(plot.status_code, 201, plot.data)
        plot_id = plot.data["id"]
        held = self.client.post(
            f"/api/organizations/{self.organization.slug}/inventory/plots/{plot_id}/hold/",
            {"reason": "Task 3 hold", "from_datetime": (timezone.now() + timedelta(minutes=1)).isoformat(), "to_datetime": (timezone.now() + timedelta(hours=1)).isoformat()},
            format="json", **self.headers(self.project_b),
        )
        self.assertEqual(held.status_code, 200, held.data)

        document = self.client.post(
            f"/api/organizations/{self.organization.slug}/documents/",
            {
                "customer": self.project_b_lead.id,
                "document_category": self.document_category.id,
                "document_name": "Identity",
                "file": SimpleUploadedFile("identity.pdf", b"%PDF-1.4 task3", content_type="application/pdf"),
            }, format="multipart", **self.headers(self.project_b),
        )
        self.assertEqual(document.status_code, 201, document.data)

        expense = self.client.post(
            "/api/expenses/",
            {"category": self.category_b.id, "amount": "100", "description": "Task 3", "date": "2026-11-01", "action": "draft"},
            format="json", **self.headers(self.project_b),
        )
        self.assertEqual(expense.status_code, 201, expense.data)

    def test_g1_item_9_admin_without_assignment_can_open_project(self):
        self.assert_project_operations_are_allowed(self.admin)

    def test_g1_item_9_settings_edit_role_without_assignment_can_open_project(self):
        self.assert_project_operations_are_allowed(self.custom_admin)

    def test_non_admin_without_assignment_is_denied_with_project_message(self):
        self.authenticate(self.restricted)
        response = self.client.get(f"/api/organizations/{self.organization.slug}/leads/", **self.headers(self.project_b))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "You are not assigned to this project.")

    def test_superuser_and_platform_admin_can_open_projects_in_both_organizations(self):
        for user, projects in ((self.superuser, (self.project_b, self.project_y)), (self.platform_admin, (self.project_b, self.project_y))):
            self.authenticate(user)
            for project in projects:
                response = self.client.get(
                    f"/api/organizations/{project.organization.slug}/leads/", **self.headers(project)
                )
                self.assertEqual(response.status_code, 200, response.data)


class Task3IsolationTests(Task3AccessBase):
    def test_gnfr_06_project_isolation_for_leads_and_plots(self):
        self.authenticate(self.admin)
        leads = self.client.get(f"/api/organizations/{self.organization.slug}/leads/", **self.headers(self.project_b))
        self.assertEqual(leads.status_code, 200)
        self.assertNotIn(self.other_lead.id, {row["id"] for row in leads.data["results"]})
        lead_detail = self.client.get(
            f"/api/organizations/{self.organization.slug}/leads/{self.other_lead.id}/", **self.headers(self.project_b)
        )
        self.assertEqual(lead_detail.status_code, 404)

        plots = self.client.get(f"/api/organizations/{self.organization.slug}/inventory/plots/", **self.headers(self.project_b))
        self.assertEqual(plots.status_code, 200)
        self.assertNotIn(self.other_plot.id, {row["id"] for row in plots.data["results"]})
        plot_detail = self.client.get(
            f"/api/organizations/{self.organization.slug}/inventory/plots/{self.other_plot.id}/", **self.headers(self.project_b)
        )
        self.assertEqual(plot_detail.status_code, 404)

    def test_fr_p0_02_rejects_foreign_and_missing_project_context(self):
        self.authenticate(self.admin)
        foreign = self.client.get(f"/api/organizations/{self.organization.slug}/leads/", **self.headers(self.project_y))
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(foreign.data["detail"], "You do not have access to this project.")
        missing = self.client.get(f"/api/organizations/{self.organization.slug}/leads/", **{"HTTP_X_PROJECT_ID": ""})
        self.assertEqual(missing.status_code, 400)


class Task3RegistrationTests(Task3AccessBase):
    def test_fr_p1_07_registration_routes_are_unavailable_without_login(self):
        before = get_user_model().objects.count()
        for path in ("/api/auth/register/", "/api/v1/auth/register/"):
            response = self.client.post(path, {"email": "new@example.com", "password": "Password1!"}, format="json", **self.headers(self.project_a))
            self.assertEqual(response.status_code, 404)
        self.assertEqual(get_user_model().objects.count(), before)


class Task3EscalationAndProjectCreationTests(Task3AccessBase):
    def test_gnfr_05_manager_cannot_escalate_members_employees_or_role_mapping(self):
        self.authenticate(self.manager)
        member_before = OrganizationMembership.objects.count()
        add_member = self.client.post(
            f"/api/organizations/{self.organization.slug}/members/",
            {"email": self.target_user.email, "role": "admin"}, format="json", **self.headers(self.project_a),
        )
        self.assertEqual(add_member.status_code, 403)
        self.assertEqual(OrganizationMembership.objects.count(), member_before)

        create_employee = self.client.post(
            f"/api/organizations/{self.organization.slug}/employees/",
            {"email": "new-admin@example.com", "temporary_password": "Password1!", "first_name": "New", "role": "admin"},
            format="json", **self.headers(self.project_a),
        )
        self.assertEqual(create_employee.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(email="new-admin@example.com").exists())

        target_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.target_user, role="telecaller", organization_role=self.roles["telecaller"]
        )
        admin_role = self.roles["admin"]
        role_patch = self.client.patch(
            f"/api/organizations/{self.organization.slug}/employees/{target_membership.id}/",
            {"role_id": admin_role.id}, format="json", **self.headers(self.project_a),
        )
        self.assertEqual(role_patch.status_code, 403)
        target_membership.refresh_from_db()
        self.assertNotEqual(target_membership.organization_role_id, admin_role.id)

    def test_fr_p0_06_only_organization_admin_can_create_a_project(self):
        for user in (self.telecaller, self.manager):
            self.authenticate(user)
            response = self.client.post(
                f"/api/organizations/{self.organization.slug}/inventory/projects/",
                {"name": f"Denied {user.username}", "code": f"DENIED-{user.id}"}, format="json", **self.headers(self.project_a),
            )
            self.assertEqual(response.status_code, 403)

        self.authenticate(self.admin)
        response = self.client.post(
            f"/api/organizations/{self.organization.slug}/inventory/projects/",
            {"name": "Created by admin", "code": "ADMIN-PROJECT"}, format="json", **self.headers(self.project_a),
        )
        self.assertEqual(response.status_code, 201, response.data)
