from decimal import Decimal
import tempfile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from organizations.models import Organization, OrganizationMembership

from .models import Expense, ExpenseCategory
from .services import cancel_expense, submit_expense


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), EXPENSE_RECEIPT_THRESHOLD=Decimal("5000"))
class Phase16ExpenseTests(TestCase):
    """FR-P16-01..06, NFR-P16-01/02 backend acceptance tests."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.employee = User.objects.create_user(username="p16-employee", password="password123")
        self.manager = User.objects.create_user(username="p16-manager", password="password123")
        self.admin = User.objects.create_user(username="p16-admin", password="password123")
        self.organization = Organization.objects.create(name="P16 Org", slug="p16-org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.employee, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN)
        self.category = ExpenseCategory.objects.create(organization=self.organization, name="Travel")

    def expense(self, amount=Decimal("100"), status=Expense.Status.DRAFT):
        return Expense.objects.create(organization=self.organization, category=self.category, amount=amount, description="Taxi", payment_method=Expense.PaymentMethod.CASH, paid_by=self.employee, submitted_by=self.employee, status=status)

    def receipt(self):
        return SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 receipt", content_type="application/pdf")

    def test_receipt_is_required_only_above_configured_threshold(self):
        low = self.expense(Decimal("100"))
        submit_expense(low, self.employee)
        self.assertEqual(low.status, Expense.Status.PENDING_APPROVAL)
        high = self.expense(Decimal("5000.01"))
        with self.assertRaises(ValidationError):
            submit_expense(high, self.employee)
        high.receipt = self.receipt(); high.save()
        submit_expense(high, self.employee)
        self.assertEqual(high.status, Expense.Status.PENDING_APPROVAL)

    def test_approved_expense_cannot_be_edited_or_deleted(self):
        expense = self.expense(status=Expense.Status.APPROVED)
        expense.description = "Tampered"
        with self.assertRaises(ValidationError):
            expense.save()
        with self.assertRaises(ValidationError):
            expense.delete()

    def test_only_admin_can_cancel_approved_expense(self):
        expense = self.expense(status=Expense.Status.APPROVED)
        with self.assertRaises(PermissionDenied):
            cancel_expense(expense, self.manager)
        cancel_expense(expense, self.admin)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.CANCELLED)
        self.assertTrue(expense.is_deleted)
