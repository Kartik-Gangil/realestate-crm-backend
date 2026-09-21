from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership

from .models import ActivityLog, ApprovalStep, Expense, ExpenseCategory, Payment, ReimbursementRequest


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), EXPENSE_RECEIPT_THRESHOLD=5000)
class ExpenseApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(username="employee", password="pass")
        self.manager = user_model.objects.create_user(username="manager", password="pass")
        self.finance = user_model.objects.create_user(username="finance", password="pass")
        self.other = user_model.objects.create_user(username="other", password="pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(organization=self.organization, user=self.employee, role="telecaller")
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role="manager")
        OrganizationMembership.objects.create(organization=self.organization, user=self.finance, role="admin")
        OrganizationMembership.objects.create(organization=self.other_organization, user=self.other, role="telecaller")
        self.category = ExpenseCategory.objects.create(organization=self.organization, name="Travel")
        self.client = APIClient()
        self.url = reverse("expenses:list")

    def payload(self, **overrides):
        data = {"organization": self.organization.slug, "category": self.category.id, "amount": "125.50", "description": "Taxi", "payment_method": "cash"}
        data.update(overrides)
        return data

    def receipt(self):
        return SimpleUploadedFile("receipt.pdf", b"pdf", content_type="application/pdf")

    def test_create_draft_and_threshold_receipt_submission(self):
        self.client.force_authenticate(self.employee)
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        expense = Expense.objects.get()
        self.assertEqual(expense.status, Expense.Status.DRAFT)
        response = self.client.post(self.url, self.payload(action="submit"), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Expense.objects.count(), 2)
        response = self.client.post(self.url, {**self.payload(action="submit"), "receipt": self.receipt()}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        submitted = Expense.objects.get(pk=response.data["id"])
        self.assertEqual(submitted.status, Expense.Status.PENDING_APPROVAL)
        self.assertEqual(submitted.approval_steps.count(), 2)

    def test_list_is_scoped_by_can_view_and_filters(self):
        own = Expense.objects.create(organization=self.organization, category=self.category, amount=Decimal("10"), description="Own taxi", payment_method="cash", paid_by=self.employee, submitted_by=self.employee)
        Expense.objects.create(organization=self.organization, category=self.category, amount=Decimal("20"), description="Team taxi", payment_method="cash", paid_by=self.manager, submitted_by=self.manager)
        self.client.force_authenticate(self.employee)
        response = self.client.get(self.url, {"search": "Own", "status": Expense.Status.DRAFT})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], own.id)
        self.client.force_authenticate(self.manager)
        response = self.client.get(self.url, {"payment_status": Expense.PaymentStatus.UNPAID})
        self.assertEqual(response.data["count"], 2)

    def test_edit_approved_is_rejected_and_cancel_soft_deletes(self):
        expense = Expense.objects.create(organization=self.organization, category=self.category, amount=Decimal("10"), description="Own taxi", payment_method="cash", paid_by=self.employee, submitted_by=self.employee, status=Expense.Status.APPROVED)
        self.client.force_authenticate(self.employee)
        detail_url = reverse("expenses:detail", args=[expense.id])
        self.assertEqual(self.client.patch(detail_url, {"description": "Changed"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("expenses:cancel", args=[expense.id]), {}, format="json").status_code, 400)
        expense.status = Expense.Status.DRAFT
        expense.save(update_fields=["status"])
        response = self.client.post(reverse("expenses:cancel", args=[expense.id]), {}, format="json")
        self.assertEqual(response.status_code, 200)
        expense.refresh_from_db()
        self.assertTrue(expense.is_deleted)
        self.assertTrue(ActivityLog.objects.filter(expense=expense, action="Cancelled").exists())

    def test_history_reads_activity_log_and_deleted_is_soft_delete_list(self):
        expense = Expense.objects.create(
            organization=self.organization, category=self.category, amount=Decimal("10"),
            description="History taxi", payment_method="cash", paid_by=self.employee,
            submitted_by=self.employee,
        )
        self.client.force_authenticate(self.employee)
        self.assertEqual(self.client.post(reverse("expenses:cancel", args=[expense.id]), {}, format="json").status_code, 200)
        history = self.client.get(reverse("expenses:history"))
        self.assertEqual(history.status_code, 200)
        cancelled = [item for item in history.data["results"] if item["action"] == "Cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["snapshot"]["expense_id"], expense.expense_id)
        deleted = self.client.get(reverse("expenses:deleted"))
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.data["count"], 1)
        self.assertEqual(self.client.get(self.url).data["count"], 0)

    def pending_expense(self, description="Pending taxi"):
        return Expense.objects.create(
            organization=self.organization, category=self.category, amount=Decimal("50"),
            description=description, payment_method="cash", paid_by=self.employee,
            submitted_by=self.employee, status=Expense.Status.PENDING_APPROVAL,
        )

    def test_manager_queue_and_approve_creates_finance_step(self):
        expense = self.pending_expense()
        ApprovalStep.objects.create(expense=expense, step_name="Submitted", status=ApprovalStep.Status.DONE, actor=self.employee)
        ApprovalStep.objects.create(expense=expense, step_name="Manager Review")
        self.client.force_authenticate(self.manager)
        queue = self.client.get(reverse("expenses:pending-approval"))
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.data["count"], 1)
        response = self.client.post(reverse("expenses:approve", args=[expense.id]), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.APPROVED)
        self.assertEqual(expense.approval_steps.get(step_name="Manager Review").status, ApprovalStep.Status.DONE)
        self.assertTrue(expense.approval_steps.filter(step_name="Finance", status=ApprovalStep.Status.PENDING).exists())
        self.assertTrue(ActivityLog.objects.filter(expense=expense, action="Approved").exists())

    def test_reject_requires_comment_and_request_changes_reopens_submitter(self):
        expense = self.pending_expense()
        ApprovalStep.objects.create(expense=expense, step_name="Manager Review")
        self.client.force_authenticate(self.manager)
        reject_url = reverse("expenses:reject", args=[expense.id])
        self.assertEqual(self.client.post(reject_url, {}, format="json").status_code, 400)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.PENDING_APPROVAL)
        changes_url = reverse("expenses:request-changes", args=[expense.id])
        self.assertEqual(self.client.post(changes_url, {"comment": "Please attach a clearer receipt."}, format="json").status_code, 200)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.CHANGES_REQUESTED)
        self.client.force_authenticate(self.employee)
        expense.receipt = self.receipt()
        expense.save()
        from .services import submit_expense
        submit_expense(expense, self.employee)
        self.assertEqual(expense.approval_steps.get(step_name="Manager Review").status, ApprovalStep.Status.PENDING)

    def test_employee_cannot_access_manager_queue_or_approve(self):
        expense = self.pending_expense()
        ApprovalStep.objects.create(expense=expense, step_name="Manager Review")
        self.client.force_authenticate(self.employee)
        self.assertEqual(self.client.get(reverse("expenses:pending-approval")).status_code, 403)
        self.assertEqual(self.client.post(reverse("expenses:approve", args=[expense.id]), {}, format="json").status_code, 403)

    def test_payment_queues_and_mark_paid(self):
        expense = Expense.objects.create(
            organization=self.organization, category=self.category, amount=Decimal("50"),
            description="Approved taxi", payment_method="cash", paid_by=self.employee,
            submitted_by=self.employee, status=Expense.Status.APPROVED,
        )
        self.client.force_authenticate(self.finance)
        unpaid = self.client.get(reverse("expenses:payments-unpaid"))
        self.assertEqual(unpaid.status_code, 200)
        self.assertEqual(unpaid.data["count"], 1)
        response = self.client.post(reverse("expenses:mark-paid", args=[expense.id]), {"payment_method": "upi", "payment_date": "2026-09-06", "reference_no": "UPI-1", "paid_amount": "50", "paid_by": self.finance.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        expense.refresh_from_db()
        self.assertEqual(expense.payment_status, Expense.PaymentStatus.PAID)
        self.assertEqual(Payment.objects.get(expense=expense).payment_method, "upi")
        self.assertEqual(self.client.get(reverse("expenses:payments-paid")).data["count"], 1)

    def test_reimbursement_advance_adjustment_required_before_approval(self):
        advance = Expense.objects.create(
            organization=self.organization, category=self.category, amount=Decimal("40"),
            description="Advance travel", payment_method="cash", paid_by=self.employee,
            submitted_by=self.employee, status=Expense.Status.APPROVED, is_advance=True,
        )
        reimbursement = ReimbursementRequest.objects.create(employee=self.employee, expense=advance, amount=Decimal("100"))
        self.client.force_authenticate(self.finance)
        approve_url = reverse("expenses:reimbursement-approve", args=[reimbursement.id])
        self.assertEqual(self.client.post(approve_url, {}, format="json").status_code, 400)
        adjust = self.client.post(reverse("expenses:reimbursement-adjust-advance", args=[reimbursement.id]), {}, format="json")
        self.assertEqual(adjust.status_code, 200, adjust.data)
        reimbursement.refresh_from_db()
        self.assertEqual(reimbursement.advance_adjusted_amount, Decimal("40"))
        self.assertEqual(self.client.post(approve_url, {}, format="json").status_code, 200)
        reimbursement.refresh_from_db()
        self.assertEqual(reimbursement.status, ReimbursementRequest.Status.APPROVED)

    def test_categories_are_finance_admin_only_and_soft_toggle(self):
        self.client.force_authenticate(self.employee)
        self.assertEqual(self.client.get(reverse("expenses:categories")).status_code, 403)
        self.client.force_authenticate(self.finance)
        response = self.client.post(reverse("expenses:categories"), {"organization": self.organization.slug, "name": "Internet", "description": "Connectivity"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        category_id = response.data["id"]
        response = self.client.patch(reverse("expenses:category-detail", args=[category_id]), {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(self.client.delete(reverse("expenses:category-detail", args=[category_id])).status_code, 405)

    def test_report_summary_scope_and_exports(self):
        Expense.objects.create(organization=self.organization, category=self.category, amount=Decimal("10"), description="Report paid", payment_method="cash", paid_by=self.employee, submitted_by=self.employee, status=Expense.Status.APPROVED, payment_status=Expense.PaymentStatus.PAID, date="2026-09-01")
        Expense.objects.create(organization=self.organization, category=self.category, amount=Decimal("20"), description="Report pending", payment_method="cash", paid_by=self.employee, submitted_by=self.employee, status=Expense.Status.APPROVED, date="2026-09-02")
        self.client.force_authenticate(self.employee)
        response = self.client.get(reverse("expenses:report-summary"), {"start": "2026-09-01", "end": "2026-09-30"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["totals"]["total_expenses"], "30.00")
        self.assertEqual(len(response.data["category_breakdown"]), 1)
        self.assertEqual(len(response.data["expenses_over_time"]), 2)
        xlsx = self.client.get(reverse("expenses:report-export"), {"format": "xlsx"})
        self.assertEqual(xlsx.status_code, 200, xlsx.data if hasattr(xlsx, "data") else xlsx.content[:200])
        self.assertEqual(xlsx["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        pdf = self.client.get(reverse("expenses:report-export"), {"format": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
