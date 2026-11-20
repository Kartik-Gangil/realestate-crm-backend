"""DM-P3-02/GNFR-05/G-4/FR-P16-02 download permission matrix."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_PDF
from documents.models import CustomerDocument, DocumentCategory, EmployeeDocument, EmployeeDocumentCategory
from expenses.models import ApprovalStep, Expense, ExpenseCategory
from inventory.models import Agreement, AgreementSignedDocument, Block, Plot, PlotBooking, Project, Registry, RegistryDocument
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission, ProjectAssignment


class FileDownloadPermissionTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Download permissions", slug="download-permissions")
        self.other_project = Project.objects.create(organization=self.organization, name="Other", code="OTHER")
        self.project = Project.objects.create(organization=self.organization, name="Main", code="MAIN")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A", code="A")
        self.plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number="A-001",
            size=Decimal("100"),
            total_price=Decimal("100000"),
            status=Plot.Status.BOOKED,
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Buyer",
            phone="9000000091",
        )
        self.booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=self.lead,
            plot=self.plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("100000"),
        )
        self.agreement = Agreement.objects.create(
            organization=self.organization,
            booking=self.booking,
            agreement_number="AGR-1",
            created_by=self.admin_user,
        ) if hasattr(self, "admin_user") else None

        self.category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")
        self.customer_document = CustomerDocument.objects.create(
            organization=self.organization,
            customer=self.lead,
            document_category=self.category,
            document_name="PAN",
            file=SimpleUploadedFile("pan.pdf", SAMPLE_PDF, content_type="application/pdf"),
            file_name="pan.pdf",
            file_size=len(SAMPLE_PDF),
            content_type="application/pdf",
            version=1,
        )
        employee_category = EmployeeDocumentCategory.objects.create(
            organization=self.organization, name="Offer letter", code="offer"
        )

        self.admin_user = self._make_admin("download-admin")
        self.employee_document = EmployeeDocument.objects.create(
            organization=self.organization,
            employee=self.admin_user.organization_memberships.get(organization=self.organization),
            document_category=employee_category,
            document_name="Offer",
            file=SimpleUploadedFile("offer.pdf", SAMPLE_PDF, content_type="application/pdf"),
            file_name="offer.pdf",
            file_size=len(SAMPLE_PDF),
            content_type="application/pdf",
            version=1,
        )
        self.agreement = Agreement.objects.create(
            organization=self.organization,
            booking=self.booking,
            agreement_number="AGR-1",
            created_by=self.admin_user,
        )
        AgreementSignedDocument.objects.create(
            agreement=self.agreement,
            file=SimpleUploadedFile("signed.pdf", SAMPLE_PDF, content_type="application/pdf"),
            original_filename="signed.pdf",
            content_type="application/pdf",
            file_size_bytes=len(SAMPLE_PDF),
            uploaded_by=self.admin_user,
        )
        self.registry = Registry.objects.create(
            organization=self.organization,
            booking=self.booking,
            registry_number="REG-1",
            consideration_amount=Decimal("100000"),
        )
        self.registry_document = RegistryDocument.objects.create(
            registry=self.registry,
            file=SimpleUploadedFile("deed.pdf", SAMPLE_PDF, content_type="application/pdf"),
            document_label="Deed",
            original_filename="deed.pdf",
            content_type="application/pdf",
            file_size_bytes=len(SAMPLE_PDF),
            uploaded_by=self.admin_user,
        )

        expense_category = ExpenseCategory.objects.create(organization=self.organization, name="Travel")
        self.expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.admin_user,
            category=expense_category,
            amount="1250.00",
            description="Taxi",
            receipt=SimpleUploadedFile("taxi.pdf", SAMPLE_PDF, content_type="application/pdf"),
        )
        self.approval_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.admin_user,
            category=expense_category,
            amount="200.00",
            description="Approval taxi",
            status=Expense.Status.PENDING_APPROVAL,
            receipt=SimpleUploadedFile("approval.pdf", SAMPLE_PDF, content_type="application/pdf"),
        )
        self.approved_expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.admin_user,
            category=expense_category,
            amount="300.00",
            description="Already approved",
            status=Expense.Status.APPROVED,
            receipt=SimpleUploadedFile("approved.pdf", SAMPLE_PDF, content_type="application/pdf"),
        )
        self.client = APIClient()

    def _permission(self, module, action):
        return Permission.objects.get(module=module, action=action)

    def _make_project_user(self, username, module, actions):
        user = get_user_model().objects.create_user(username=username, password="pw-123456")
        role = OrganizationRole.objects.create(organization=self.organization, name=username, code=username)
        role.permissions.set([self._permission(module, action) for action in actions])
        membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMembership.Role.MANAGER,
            organization_role=role,
            access_scope=OrganizationMembership.AccessScope.ALL,
        )
        ProjectAssignment.objects.create(membership=membership, project=self.project, role=role)
        return user

    def _make_org_user(self, username, module, actions):
        user = get_user_model().objects.create_user(username=username, password="pw-123456")
        role = OrganizationRole.objects.create(organization=self.organization, name=username, code=username)
        role.permissions.set([self._permission(module, action) for action in actions])
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMembership.Role.MANAGER,
            organization_role=role,
            access_scope=OrganizationMembership.AccessScope.ALL,
        )
        return user

    def _make_admin(self, username):
        user = get_user_model().objects.create_user(username=username, password="pw-123456")
        role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Organization admin",
            code=username,
            is_system=True,
        )
        role.permissions.set(Permission.objects.all())
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMembership.Role.ADMIN,
            organization_role=role,
            access_scope=OrganizationMembership.AccessScope.ALL,
        )
        return user

    def _get(self, user, path, *, project=True):
        self.client.force_authenticate(user)
        headers = {"HTTP_X_PROJECT_ID": str(self.project.id)} if project else {}
        return self.client.get(path, **headers)

    def test_customer_document_requires_export_not_view(self):
        view_user = self._make_project_user("customer-view", "documents", ["view"])
        export_user = self._make_project_user("customer-export", "documents", ["view", "export"])
        path = f"/api/organizations/{self.organization.slug}/documents/{self.customer_document.id}/download/"
        self.assertEqual(self._get(view_user, path).status_code, 403)
        assert_protected_download(self, self._get(export_user, path), SAMPLE_PDF, "application/pdf")
        assert_protected_download(self, self._get(self.admin_user, path), SAMPLE_PDF, "application/pdf")

    def test_employee_document_requires_organization_employees_export(self):
        view_user = self._make_org_user("employee-view", "employees", ["view"])
        export_user = self._make_org_user("employee-export", "employees", ["view", "export"])
        path = f"/api/organizations/{self.organization.slug}/employee-documents/{self.employee_document.id}/download/"
        self.assertEqual(self._get(view_user, path, project=False).status_code, 403)
        assert_protected_download(self, self._get(export_user, path, project=False), SAMPLE_PDF, "application/pdf")
        assert_protected_download(self, self._get(self.admin_user, path, project=False), SAMPLE_PDF, "application/pdf")

    def test_agreement_signed_copy_requires_plots_export(self):
        view_user = self._make_project_user("agreement-view", "plots", ["view"])
        export_user = self._make_project_user("agreement-export", "plots", ["view", "export"])
        path = f"/api/organizations/{self.organization.slug}/inventory/agreements/{self.agreement.id}/download-signed/"
        self.assertEqual(self._get(view_user, path).status_code, 403)
        assert_protected_download(self, self._get(export_user, path), SAMPLE_PDF, "application/pdf")
        assert_protected_download(self, self._get(self.admin_user, path), SAMPLE_PDF, "application/pdf")

    def test_registry_document_requires_registry_export(self):
        view_user = self._make_project_user("registry-view", "registry", ["view"])
        export_user = self._make_project_user("registry-export", "registry", ["view", "export"])
        path = f"/api/organizations/{self.organization.slug}/registries/{self.registry.id}/documents/{self.registry_document.id}/download/"
        self.assertEqual(self._get(view_user, path).status_code, 403)
        assert_protected_download(self, self._get(export_user, path), SAMPLE_PDF, "application/pdf")
        assert_protected_download(self, self._get(self.admin_user, path), SAMPLE_PDF, "application/pdf")

    def test_expense_receipt_requires_export_except_for_pending_or_recorded_reviewer(self):
        view_user = self._make_project_user("expense-view", "expenses", ["view"])
        export_user = self._make_project_user("expense-export", "expenses", ["view", "export"])
        approver = self._make_project_user("expense-approver", "expenses", ["approve"])
        path = f"/api/expenses/{self.expense.id}/receipt/"
        self.assertEqual(self._get(view_user, path).status_code, 403)
        assert_protected_download(self, self._get(export_user, path), SAMPLE_PDF, "application/pdf")
        assert_protected_download(self, self._get(self.admin_user, path), SAMPLE_PDF, "application/pdf")

        approval_path = f"/api/expenses/{self.approval_expense.id}/receipt/"
        assert_protected_download(self, self._get(approver, approval_path), SAMPLE_PDF, "application/pdf")
        self.assertEqual(self._get(approver, f"/api/expenses/{self.approved_expense.id}/receipt/").status_code, 403)

        ApprovalStep.objects.create(
            expense=self.approved_expense,
            step_name="Manager Review",
            actor=approver,
            status=ApprovalStep.Status.DONE,
        )
        assert_protected_download(
            self,
            self._get(approver, f"/api/expenses/{self.approved_expense.id}/receipt/"),
            SAMPLE_PDF,
            "application/pdf",
        )

    def test_project_without_access_stays_forbidden_or_not_found(self):
        export_user = self._make_project_user("project-export", "documents", ["view", "export"])
        path = f"/api/organizations/{self.organization.slug}/documents/{self.customer_document.id}/download/"
        self.client.force_authenticate(export_user)
        response = self.client.get(path, HTTP_X_PROJECT_ID=str(self.other_project.id))
        self.assertIn(response.status_code, {403, 404})
