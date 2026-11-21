from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from organizations.models import OrganizationMembership, Permission, ProjectAssignment

from .models import Expense, ExpenseCategory, Payment


class GroupEPhase16Tests(TestCase):
    """Phase 16 / FR-P16-02, FR-P16-04..06 and API/NFR-P16-01..02."""

    def setUp(self):
        self.organization = make_organization("group-e-p16")
        self.project = make_project(self.organization, "P16")
        self.employee_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.accounts_membership = make_member(self.organization, role="accounts", projects=[self.project])
        self.employee = self.employee_membership.user
        self.manager = self.manager_membership.user
        self.admin = self.admin_membership.user
        self.accounts = self.accounts_membership.user
        self.category = ExpenseCategory.objects.create(organization=self.organization, project=self.project, name="Travel")
        self.employee_client = APIClient()
        self.manager_client = APIClient()
        self.accounts_client = APIClient()
        self.admin_client = APIClient()
        self.employee_client.force_authenticate(self.employee)
        self.manager_client.force_authenticate(self.manager)
        self.accounts_client.force_authenticate(self.accounts)
        self.admin_client.force_authenticate(self.admin)
        for code in ("expenses.view_own", "expenses.edit_own", "expenses.submit"):
            module, action = code.split(".")
            permission, _ = Permission.objects.get_or_create(module=module, action=action, defaults={"name": code})
            self.employee_membership.organization_role.permissions.add(permission)

    def url(self, expense_id=None, action=""):
        base = f"/api/v1/expenses/"
        return f"{base}{expense_id}/{action}" if expense_id else base

    def headers(self):
        return {"HTTP_X_PROJECT_ID": str(self.project.id)}

    def create_expense(self, status=Expense.Status.DRAFT):
        return Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.employee,
            category=self.category,
            amount=Decimal("1250.00"),
            description="Group E expense",
            status=status,
        )

    def test_fr_p16_02_and_api_p16_05_submit_approve_reimburse_requires_reference_and_is_idempotent(self):
        response = self.employee_client.post(
            self.url(),
            {"category_id": self.category.id, "amount": "1250.00", "description": "Browser expense", "action": "submit"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.data)
        expense_id = response.data["data"]["id"]
        approved = self.manager_client.post(f"{self.url(expense_id)}approve/", {}, format="json", **self.headers())
        self.assertEqual(approved.status_code, 200, approved.data)
        missing_reference = self.accounts_client.post(
            f"{self.url(expense_id)}reimburse/", {}, format="json", **self.headers()
        )
        self.assertEqual(missing_reference.status_code, 400, missing_reference.data)
        reimbursed = self.accounts_client.post(
            f"{self.url(expense_id)}reimburse/", {"transaction_reference": "TXN-GE-001"}, format="json", **self.headers()
        )
        self.assertEqual(reimbursed.status_code, 200, reimbursed.data)
        self.assertEqual(reimbursed.data["data"]["status"], Expense.Status.REIMBURSED)
        self.assertEqual(reimbursed.data["data"]["reimbursement_reference"], "TXN-GE-001")
        second = self.accounts_client.post(
            f"{self.url(expense_id)}reimburse/", {"transaction_reference": "TXN-GE-002"}, format="json", **self.headers()
        )
        self.assertEqual(second.status_code, 409, second.data)

    def test_fr_p16_06_submitter_cannot_approve_own_expense_claim(self):
        permission, _ = Permission.objects.get_or_create(
            module="expenses", action="approve", defaults={"name": "Approve expenses"}
        )
        self.employee_membership.organization_role.permissions.add(permission)
        expense = self.create_expense(status=Expense.Status.PENDING_APPROVAL)

        response = self.employee_client.post(
            f"{self.url(expense.id)}approve/", {}, format="json", **self.headers()
        )

        self.assertEqual(response.status_code, 403, response.data)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.PENDING_APPROVAL)

    def test_fr_p16_06_wrong_role_cannot_reimburse_and_one_locked_transaction_records_actor(self):
        expense = self.create_expense(status=Expense.Status.APPROVED)
        denied = self.employee_client.post(
            f"{self.url(expense.id)}reimburse/", {"transaction_reference": "TXN-GE-003"}, format="json", **self.headers()
        )
        self.assertEqual(denied.status_code, 403, denied.data)
        response = self.accounts_client.post(
            f"{self.url(expense.id)}reimburse/", {"transaction_reference": "TXN-GE-004"}, format="json", **self.headers()
        )
        self.assertEqual(response.status_code, 200, response.data)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.REIMBURSED)
        self.assertEqual(expense.reimbursed_by_id, self.accounts.id)
        self.assertEqual(Payment.objects.filter(expense=expense).count(), 1)

    def test_fr_p16_04_admin_only_cancel_and_no_edits_after_approval(self):
        expense = self.create_expense(status=Expense.Status.APPROVED)
        forbidden_edit = self.employee_client.patch(
            f"{self.url(expense.id)}", {"description": "Changed"}, format="json", **self.headers()
        )
        self.assertEqual(forbidden_edit.status_code, 400, forbidden_edit.data)
        forbidden_cancel = self.manager_client.post(f"{self.url(expense.id)}cancel/", {}, format="json", **self.headers())
        self.assertEqual(forbidden_cancel.status_code, 403, forbidden_cancel.data)
        cancelled = self.admin_client.post(f"{self.url(expense.id)}cancel/", {}, format="json", **self.headers())
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["data"]["status"], Expense.Status.CANCELLED)

    def test_task_p16_001_approved_paid_migration_keeps_reference_and_supports_dry_run(self):
        expense = self.create_expense(status=Expense.Status.APPROVED)
        Payment.objects.create(
            expense=expense,
            payment_method=Expense.PaymentMethod.BANK_TRANSFER,
            reference_no="OLD-REF-001",
            paid_amount=expense.amount,
            paid_by=self.admin,
        )
        Expense.objects.filter(pk=expense.pk).update(payment_status=Expense.PaymentStatus.PAID)
        output = StringIO()
        call_command("migrate_paid_expenses", "--dry-run", stdout=output)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.APPROVED)
        self.assertIn("1", output.getvalue())
        call_command("migrate_paid_expenses", stdout=StringIO())
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.REIMBURSED)
        self.assertEqual(expense.reimbursement_reference, "OLD-REF-001")

