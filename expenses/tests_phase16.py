"""Phase 16 regression tests for the expense workflow."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.samples import SAMPLE_PDF
from inventory.models import Project
from system_settings.models import SystemParameter

from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission
from .models import Expense, ExpenseCategory
from django.core.files.uploadedfile import SimpleUploadedFile


class ExpensePhase16WorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(username="expense-employee", email="employee@example.com")
        self.manager = user_model.objects.create_user(username="expense-manager", email="manager@example.com")
        self.admin = user_model.objects.create_user(username="expense-admin-phase16", email="admin-phase16@example.com")
        self.organization = Organization.objects.create(name="Phase 16 Org", slug="phase-16-org")
        self.project = Project.objects.create(organization=self.organization, name="Phase 16 Project", code="P16")
        self.other_project = Project.objects.create(organization=self.organization, name="Other Project", code="P16-OTHER")

        def role(code, permissions):
            item = OrganizationRole.objects.create(organization=self.organization, name=code.title(), code=code)
            item.permissions.set([
                Permission.objects.get_or_create(module=module, action=action, defaults={"name": f"{module}.{action}"})[0]
                for module, action in (permission.split(".", 1) for permission in permissions)
            ])
            return item

        employee_role = role("telecaller", ["expenses.view_own", "expenses.edit_own", "expenses.submit"])
        manager_role = role("manager", ["expenses.view_team", "expenses.approve", "expenses.reject"])
        admin_role = role("admin", [
            "expenses.view_team", "expenses.approve", "expenses.manage_categories",
            "expenses.process_payment", "expenses.mark_paid", "expenses.process_reimbursement", "expenses.reports",
        ])
        OrganizationMembership.objects.create(organization=self.organization, user=self.employee, role="telecaller", organization_role=employee_role)
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role="manager", organization_role=manager_role)
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role="admin", organization_role=admin_role)
        self.category = ExpenseCategory.objects.create(organization=self.organization, project=self.project, name="Travel")
        self.client = APIClient()

    def auth(self, user, project=None):
        self.client.force_authenticate(user)
        return {"HTTP_X_PROJECT_ID": str((project or self.project).id)}

    def receipt(self):
        return SimpleUploadedFile("receipt.pdf", SAMPLE_PDF, content_type="application/pdf")

    def create_submitted(self, amount="125.00"):
        response = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": amount,
                "description": "Submitted taxi",
                "date": "2026-09-28",
                "action": "submit",
                "receipt": self.receipt(),
            },
            format="multipart",
            **self.auth(self.employee),
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Expense.objects.get(pk=response.data["data"]["id"])

    def test_employee_can_submit_manager_can_approve_and_reject_requires_reason(self):
        draft = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": "125.00",
                "description": "Draft taxi",
                "date": "2026-09-28",
                "action": "draft",
            },
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(draft.status_code, 201, draft.data)
        self.assertEqual(draft.data["data"]["status"], Expense.Status.DRAFT)

        submitted = self.create_submitted()
        self.assertEqual(submitted.status, Expense.Status.PENDING_APPROVAL)

        approved = self.client.post(f"/api/expenses/{submitted.id}/approve/", {}, format="json", **self.auth(self.manager))
        self.assertEqual(approved.status_code, 200, approved.data)
        submitted.refresh_from_db()
        self.assertEqual(submitted.status, Expense.Status.APPROVED)

        rejected = self.create_submitted()
        no_reason = self.client.post(f"/api/expenses/{rejected.id}/reject/", {}, format="json", **self.auth(self.manager))
        self.assertEqual(no_reason.status_code, 400)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Expense.Status.PENDING_APPROVAL)

        with_reason = self.client.post(
            f"/api/expenses/{rejected.id}/reject/",
            {"reason": "Receipt is not readable."},
            format="json",
            **self.auth(self.manager),
        )
        self.assertEqual(with_reason.status_code, 200, with_reason.data)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Expense.Status.REJECTED)
        self.assertEqual(with_reason.data["data"]["rejection_reason"], "Receipt is not readable.")

    def test_receipt_threshold_comes_from_system_parameter(self):
        SystemParameter.objects.create(
            organization=self.organization,
            parameter_key="expense_receipt_threshold",
            parameter_name="Expense receipt threshold",
            value="1000",
            data_type=SystemParameter.DataType.DECIMAL,
        )
        response = self.client.post(
            "/api/expenses/",
            {
                "category": self.category.id,
                "amount": "1001.00",
                "description": "Threshold test",
                "date": "2026-09-28",
                "action": "submit",
            },
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("receipt", response.data)

    def test_approved_expense_cannot_be_edited_and_project_scope_is_enforced(self):
        expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("100.00"),
            description="Approved expense",
            status=Expense.Status.APPROVED,
        )
        edit = self.client.patch(
            f"/api/expenses/{expense.id}/",
            {"description": "Changed"},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(edit.status_code, 400)

        other_project = self.client.get(
            f"/api/expenses/{expense.id}/",
            **self.auth(self.employee, self.other_project),
        )
        self.assertEqual(other_project.status_code, 404)

    def test_reject_and_mark_paid_require_their_explicit_permissions(self):
        user_model = get_user_model()
        rejector = user_model.objects.create_user(username="expense-rejector", email="rejector@example.com")
        reject_permission, _ = Permission.objects.get_or_create(
            module="expenses", action="reject", defaults={"name": "Reject expenses"}
        )
        rejector_role = OrganizationRole.objects.create(
            organization=self.organization, name="Expense Rejector", code="expense-rejector"
        )
        rejector_role.permissions.add(reject_permission)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=rejector,
            role="expense-rejector",
            organization_role=rejector_role,
        )

        submitted = self.create_submitted()
        denied_reject = self.client.post(
            f"/api/expenses/{submitted.id}/reject/",
            {"reason": "Not eligible."},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(denied_reject.status_code, 403)

        allowed_reject = self.client.post(
            f"/api/expenses/{submitted.id}/reject/",
            {"reason": "Not eligible."},
            format="json",
            **self.auth(rejector),
        )
        self.assertEqual(allowed_reject.status_code, 200, allowed_reject.data)

        paid_expense = self.create_submitted()
        approved = self.client.post(
            f"/api/expenses/{paid_expense.id}/approve/",
            {},
            format="json",
            **self.auth(self.manager),
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        processor = user_model.objects.create_user(username="expense-processor", email="processor@example.com")
        mark_paid_permission, _ = Permission.objects.get_or_create(
            module="expenses", action="mark_paid", defaults={"name": "Mark expenses as paid"}
        )
        processor_role = OrganizationRole.objects.create(
            organization=self.organization, name="Expense Processor", code="expense-processor"
        )
        processor_role.permissions.add(mark_paid_permission)
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=processor,
            role="expense-processor",
            organization_role=processor_role,
        )

        denied_payment = self.client.post(
            f"/api/expenses/{paid_expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(self.employee),
        )
        self.assertEqual(denied_payment.status_code, 403)

        allowed_payment = self.client.post(
            f"/api/expenses/{paid_expense.id}/mark-paid/",
            {"paid_amount": "125.00", "payment_method": "cash"},
            format="json",
            **self.auth(processor),
        )
        self.assertEqual(allowed_payment.status_code, 201, allowed_payment.data)

    def test_org_scoped_expense_creation_without_active_project_does_not_500(self):
        category = ExpenseCategory.objects.create(
            organization=self.organization,
            project=None,
            name="Office",
        )
        self.client.force_authenticate(self.employee)

        response = self.client.post(
            "/api/expenses/",
            {
                "category": category.id,
                "amount": "125.00",
                "description": "Office supplies",
                "date": "2026-09-28",
                "action": "draft",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], Expense.Status.DRAFT)
