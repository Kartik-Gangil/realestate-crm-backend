import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from organizations.models import ProjectScopedModel


MAX_RECEIPT_SIZE = 5 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = ["jpg", "jpeg", "png", "pdf"]


def receipt_upload_path(instance, filename):
    safe_name = os.path.basename(filename).replace(" ", "_") or "receipt"
    return f"expenses/{instance.organization.slug}/{instance.expense_id or 'new'}/{safe_name}"


def validate_receipt_size(value):
    if value and value.size > MAX_RECEIPT_SIZE:
        raise ValidationError("Receipt must not exceed 5 MB.")


class ExpenseCategory(ProjectScopedModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="expense_categories")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "project", "name"], name="expenses_category_org_name_unique"), models.UniqueConstraint(fields=["organization", "name"], condition=models.Q(project__isnull=True), name="expenses_category_org_name_legacy")]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class Expense(ProjectScopedModel):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        UPI = "upi", "UPI"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField(default=timezone.localdate)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    description = models.TextField()
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_paid_fronted")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_submitted")
    receipt = models.FileField(upload_to=receipt_upload_path, blank=True, null=True, validators=[FileExtensionValidator(ALLOWED_RECEIPT_EXTENSIONS), validate_receipt_size])
    notes = models.TextField(blank=True)
    project_reference = models.CharField(max_length=255, blank=True)
    is_advance = models.BooleanField(default=False)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "payment_status"]),
            models.Index(fields=["organization", "is_deleted"]),
        ]

    @property
    def expense_id(self):
        return f"EXP{self.pk:03d}" if self.pk else None

    def clean(self):
        super().clean()
        errors = {}
        if self.category_id and self.category.organization_id != self.organization_id:
            errors["category"] = "Category must belong to the same organization."
        if self.receipt:
            extension = os.path.splitext(self.receipt.name)[1].lower().lstrip(".")
            if extension not in ALLOWED_RECEIPT_EXTENSIONS:
                errors["receipt"] = "Receipt must be JPG, PNG, or PDF."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and self.status == self.Status.APPROVED and not getattr(self, "_allow_mutation", False):
            previous = type(self).objects.get(pk=self.pk)
            immutable = ("organization_id", "project_id", "date", "category_id", "amount", "description", "payment_method", "paid_by_id", "submitted_by_id", "receipt", "notes", "project_reference", "is_advance")
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Approved expenses are immutable; use the cancellation workflow.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and self.status == self.Status.APPROVED and not getattr(self, "_allow_mutation", False):
            raise ValidationError("Approved expenses cannot be deleted; use the cancellation workflow.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.expense_id or "Unsaved expense"


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
    payment_method = models.CharField(max_length=20, choices=Expense.PaymentMethod.choices)
    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="payment")
    payment_status = models.CharField(max_length=12, choices=Expense.PaymentStatus.choices, default=Expense.PaymentStatus.UNPAID)
    payment_date = models.DateField(null=True, blank=True)
    reference_no = models.CharField(max_length=100, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_payments_processed")
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])


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


class ActivityLog(models.Model):
    expense = models.ForeignKey(Expense, null=True, blank=True, on_delete=models.SET_NULL, related_name="activity_logs")
    action = models.CharField(max_length=32)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_activity_logs")
    action_date = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-action_date", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Activity logs are append-only.")
        return super().save(*args, **kwargs)
