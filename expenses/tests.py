from decimal import Decimal
import tempfile

from django.core import management
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from organizations.models import Organization, OrganizationMembership

from .models import ActivityLog, Expense, ExpenseCategory
from .services import can_approve, can_edit, can_view, submit_expense


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), EXPENSE_RECEIPT_THRESHOLD=5000)
class ExpenseFoundationTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        self.employee = user_model.objects.create_user(username="employee", password="pass")
        self.manager = user_model.objects.create_user(username="manager", password="pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        OrganizationMembership.objects.create(organization=self.organization, user=self.employee, role="telecaller")
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role="manager")
        self.category = ExpenseCategory.objects.create(organization=self.organization, name="Travel")
        self.expense = Expense.objects.create(
            organization=self.organization, category=self.category, amount=Decimal("100.00"),
            description="Taxi", payment_method=Expense.PaymentMethod.CASH,
            paid_by=self.employee, submitted_by=self.employee,
        )

    def receipt(self, name="receipt.pdf", content=b"pdf"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_expense_id_and_organization_isolation(self):
        self.assertEqual(self.expense.expense_id, f"EXP{self.expense.pk:03d}")
        other = Organization.objects.create(name="Other", slug="other")
        other_category = ExpenseCategory.objects.create(organization=other, name="Travel")
        self.expense.category = other_category
        with self.assertRaises(ValidationError):
            self.expense.full_clean()

    def test_receipt_required_only_on_submission_and_submission_logs_workflow(self):
        self.assertTrue(can_edit(self.employee, self.expense))
        submit_expense(self.expense, self.employee)
        self.expense.refresh_from_db()
        self.assertEqual(self.expense.status, Expense.Status.PENDING_APPROVAL)
        self.assertTrue(self.expense.approval_steps.filter(step_name="Manager Review").exists())
        self.assertTrue(ActivityLog.objects.filter(expense=self.expense, action="Submitted").exists())
        self.assertTrue(can_approve(self.manager, self.expense))

    def test_receipt_extension_and_size_are_validated(self):
        self.expense.receipt = self.receipt("receipt.exe")
        with self.assertRaises(ValidationError):
            self.expense.full_clean()
        self.expense.receipt = self.receipt("receipt.pdf", b"x" * (5 * 1024 * 1024 + 1))
        with self.assertRaises(ValidationError):
            self.expense.full_clean()

    def test_default_categories_command_is_idempotent(self):
        management.call_command("seed_expense_categories", organization="acme", stdout=None)
        management.call_command("seed_expense_categories", organization="acme", stdout=None)
        self.assertEqual(ExpenseCategory.objects.filter(organization=self.organization).count(), 5)
