import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone


MAX_RECEIPT_SIZE = 5 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = ["jpg", "jpeg", "png", "pdf"]


def receipt_upload_path(instance, filename):
    safe_name = os.path.basename(filename).replace(" ", "_") or "receipt"
    return f"expenses/{instance.organization.slug}/{instance.expense_id or 'new'}/{safe_name}"


def validate_receipt_size(value):
    if value and value.size > MAX_RECEIPT_SIZE:
        raise ValidationError("Receipt must not exceed 5 MB.")


class ExpenseCategory(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="expense_categories"
    )
    project = models.ForeignKey(
        "inventory.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="expense_categories"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "project", "name"],
                name="expenses_category_org_project_name_unique",
            ),
        ]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class Expense(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        UPI = "upi", "UPI"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="expenses")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="expenses")
    expense_id = models.CharField(max_length=32, unique=True, editable=False)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_expenses")
    date = models.DateField(default=timezone.localdate)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    description = models.TextField()
    notes = models.TextField(blank=True)
    project_reference = models.CharField(max_length=150, blank=True)
    payment_method = models.CharField(max_length=32, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="paid_expenses")
    is_advance = models.BooleanField(default=False)
    receipt = models.FileField(
        upload_to=receipt_upload_path, null=True, blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"]), validate_receipt_size],
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    rejection_reason = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "project", "status"], name="expenses_org_proj_status_idx"),
            models.Index(fields=["organization", "project", "payment_status"], name="expenses_org_proj_pay_idx"),
            models.Index(fields=["organization", "project", "is_deleted"], name="expenses_org_proj_del_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_allow_mutation", False):
            previous = type(self).objects.get(pk=self.pk)
            if previous.status == self.Status.APPROVED:
                immutable = (
                    "organization_id", "project_id", "date", "category_id", "amount", "description",
                    "payment_method", "paid_by_id", "submitted_by_id", "receipt", "notes", "project_reference",
                    "is_advance",
                )
                if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                    raise ValidationError("Approved expenses are immutable; use the cancellation workflow.")
        if not self.expense_id:
            self.expense_id = f"EXP-{self.organization_id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
        return super().save(*args, **kwargs)


class ApprovalStep(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Done"
        REJECTED = "rejected", "Rejected"

    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="approval_steps")
    step_name = models.CharField(max_length=80)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_approval_steps")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    acted_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]


class Payment(models.Model):
    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="payment")
    payment_status = models.CharField(max_length=12, choices=Expense.PaymentStatus.choices, default=Expense.PaymentStatus.PAID)
    payment_method = models.CharField(max_length=32, choices=Expense.PaymentMethod.choices)
    payment_date = models.DateField(null=True, blank=True)
    reference_no = models.CharField(max_length=100, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_payments_processed")
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)


class ReimbursementRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_reimbursement_requests")
    expense = models.ForeignKey(Expense, null=True, blank=True, on_delete=models.SET_NULL, related_name="reimbursement_requests")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    requested_on = models.DateTimeField(auto_now_add=True)
    resolved_on = models.DateTimeField(null=True, blank=True)
    advance_adjusted_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    transaction_reference = models.CharField(max_length=100, blank=True)


class ActivityLog(models.Model):
    expense = models.ForeignKey(Expense, null=True, blank=True, on_delete=models.SET_NULL, related_name="activity_logs")
    action = models.CharField(max_length=32)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_activity_logs")
    action_date = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-action_date", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Activity logs are append-only.")
        return super().save(*args, **kwargs)
