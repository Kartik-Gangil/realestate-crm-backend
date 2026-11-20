from django.test import TestCase
from rest_framework.test import APIClient

from documents.models import CustomerDocument, DocumentCategory
from expenses.models import Expense, ExpenseCategory
from inventory.models import Block, Plot
from leads.models import Lead
from core.tests.factories import make_member, make_organization, make_project

from .models import Department, OrganizationMembership, OrganizationRole, Permission, ProjectAssignment


class FullCrmDataScopeTests(TestCase):
    """GNFR-06/FR-P3-07: access scope must protect CRM rows, not only employees."""

    def setUp(self):
        self.organization = make_organization("acme")
        self.sales = Department.objects.create(organization=self.organization, name="Sales")
        self.finance = Department.objects.create(organization=self.organization, name="Finance")
        self.role = OrganizationRole.objects.create(
            organization=self.organization, name="Scoped Viewer", code="scoped-viewer"
        )
        permissions = [
            Permission.objects.get_or_create(module=module, action="view", defaults={"name": f"View {module}"})[0]
            for module in ("leads", "expenses", "plots", "documents")
        ]
        self.role.permissions.set(permissions)

        self.project = make_project(self.organization, "MAIN")
        self.owner_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.same_department_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.other_department_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.owner = self.owner_membership.user
        self.same_department_user = self.same_department_membership.user
        self.other_department_user = self.other_department_membership.user
        for membership, department in (
            (self.owner_membership, self.sales),
            (self.same_department_membership, self.sales),
            (self.other_department_membership, self.finance),
        ):
            membership.organization_role = self.role
            membership.department = department
            membership.save(update_fields=["organization_role", "department"])
            ProjectAssignment.objects.filter(membership=membership, project=self.project).update(role=self.role)
        self.owner_membership.access_scope = OrganizationMembership.AccessScope.OWN
        self.owner_membership.save(update_fields=["access_scope"])
        self.owner_lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Owner",
            phone="9000000001",
            assigned_membership=self.owner_membership,
        )
        self.same_department_lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Teammate",
            phone="9000000002",
            assigned_membership=self.same_department_membership,
        )
        self.other_department_lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Finance",
            phone="9000000003",
            assigned_membership=self.other_department_membership,
        )
        self.category = ExpenseCategory.objects.create(
            organization=self.organization, project=self.project, name="Travel"
        )
        self.owner_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.owner,
            category=self.category,
            amount="100.00",
            description="Owner expense",
        )
        self.other_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.other_department_user,
            paid_by=self.owner,
            category=self.category,
            amount="200.00",
            description="Finance expense",
        )
        self.block = Block.objects.create(
            organization=self.organization, project=self.project, name="Block A", code="A"
        )
        self.owner_plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-001",
            size="100",
            rate_per_sq_unit="10",
            total_price="1000",
            created_by=self.owner,
        )
        self.other_plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-002",
            size="100",
            rate_per_sq_unit="10",
            total_price="1000",
            created_by=self.other_department_user,
        )
        self.category_documents = DocumentCategory.objects.create(
            organization=self.organization, name="Identity", code="identity"
        )
        self.owner_document = CustomerDocument.objects.create(
            organization=self.organization,
            customer=self.owner_lead,
            document_category=self.category_documents,
            document_name="Owner identity",
            file="documents/owner.pdf",
            file_name="owner.pdf",
            file_size=10,
            content_type="application/pdf",
            version=1,
            uploaded_by=self.owner,
        )
        self.other_document = CustomerDocument.objects.create(
            organization=self.organization,
            customer=self.other_department_lead,
            document_category=self.category_documents,
            document_name="Finance identity",
            file="documents/finance.pdf",
            file_name="finance.pdf",
            file_size=10,
            content_type="application/pdf",
            version=1,
            uploaded_by=self.other_department_user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def project_headers(self):
        return {"HTTP_X_PROJECT_ID": str(self.project.id)}

    def test_own_scope_filters_leads_plots_and_documents_but_not_expenses(self):
        leads = self.client.get("/api/organizations/acme/leads/", **self.project_headers())
        self.assertEqual(leads.status_code, 200)
        self.assertEqual({item["id"] for item in leads.data["results"]}, {self.owner_lead.id})
        self.assertEqual(
            self.client.get(
                f"/api/organizations/acme/leads/{self.other_department_lead.id}/",
                **self.project_headers(),
            ).status_code,
            404,
        )

        expenses = self.client.get("/api/expenses/", **self.project_headers())
        self.assertEqual(expenses.status_code, 200)
        self.assertEqual(
            {item["id"] for item in expenses.data["data"]["results"]},
            {self.owner_expense.id, self.other_expense.id},
        )

        plots = self.client.get("/api/organizations/acme/inventory/plots/", **self.project_headers())
        self.assertEqual(plots.status_code, 200)
        self.assertEqual({item["id"] for item in plots.data["results"]}, {self.owner_plot.id})

        documents = self.client.get("/api/organizations/acme/documents/", **self.project_headers())
        self.assertEqual(documents.status_code, 200)
        self.assertEqual({item["id"] for item in documents.data["results"]}, {self.owner_document.id})

    def test_department_scope_includes_same_department_but_expenses_use_module_permissions(self):
        self.owner_membership.access_scope = OrganizationMembership.AccessScope.DEPARTMENT
        self.owner_membership.save(update_fields=["access_scope"])

        leads = self.client.get("/api/organizations/acme/leads/", **self.project_headers())
        self.assertEqual(leads.status_code, 200)
        self.assertEqual(
            {item["id"] for item in leads.data["results"]},
            {self.owner_lead.id, self.same_department_lead.id},
        )

        expenses = self.client.get("/api/expenses/", **self.project_headers())
        self.assertEqual(expenses.status_code, 200)
        self.assertEqual(
            {item["id"] for item in expenses.data["data"]["results"]},
            {self.owner_expense.id, self.other_expense.id},
        )

    def test_all_scope_preserves_full_project_visibility(self):
        self.owner_membership.access_scope = OrganizationMembership.AccessScope.ALL
        self.owner_membership.save(update_fields=["access_scope"])

        leads = self.client.get("/api/organizations/acme/leads/", **self.project_headers())
        self.assertEqual(leads.status_code, 200)
        self.assertEqual(
            {item["id"] for item in leads.data["results"]},
            {self.owner_lead.id, self.same_department_lead.id, self.other_department_lead.id},
        )

    def test_explicit_team_view_permission_overrides_record_scope(self):
        team_view, _ = Permission.objects.get_or_create(
            module="leads", action="view_team", defaults={"name": "View lead team"}
        )
        self.role.permissions.add(team_view)

        leads = self.client.get("/api/organizations/acme/leads/", **self.project_headers())
        self.assertEqual(leads.status_code, 200)
        self.assertEqual(
            {item["id"] for item in leads.data["results"]},
            {self.owner_lead.id, self.same_department_lead.id, self.other_department_lead.id},
        )
