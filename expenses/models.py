import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone


MAX_RECEIPT_SIZE = 5 * 1024 * 1024


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
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

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
    payment_method = models.CharField(max_length=32, default="cash")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="paid_expenses")
    is_advance = models.BooleanField(default=False)
    receipt = models.FileField(
        upload_to=receipt_upload_path, null=True, blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"]), validate_receipt_size],
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(max_length=12, default="unpaid")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if not self.expense_id:
            self.expense_id = f"EXP-{self.organization_id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
        return super().save(*args, **kwargs)
