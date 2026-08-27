import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import get_valid_filename


def customer_document_upload_path(instance, filename):
    """Storage-neutral, non-user-controlled document object name."""
    safe_name = get_valid_filename(os.path.basename(filename)) or "document"
    return "documents/{}/{}/{}/{}_{}".format(
        instance.organization.slug, instance.customer_id, instance.document_category.code,
        uuid.uuid4().hex, safe_name,
    )


def employee_document_upload_path(instance, filename):
    safe_name = get_valid_filename(os.path.basename(filename)) or "document"
    return "employee_documents/{}/{}/{}/{}_{}".format(instance.organization.slug, instance.employee_id, instance.document_category.code, uuid.uuid4().hex, safe_name)


class DocumentCategory(models.Model):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="document_categories")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="documents_category_org_code_unique")]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class CustomerDocumentRequirement(models.Model):
    # The existing CRM calls the customer entity Lead; APIs retain the customer term.
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customer_document_requirements")
    customer = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="document_requirements")
    document_category = models.ForeignKey(DocumentCategory, on_delete=models.PROTECT, related_name="customer_requirements")
    is_mandatory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "customer", "document_category"], name="documents_requirement_unique")]

    def clean(self):
        errors = {}
        if self.customer_id and self.customer.organization_id != self.organization_id:
            errors["customer"] = "Customer must belong to this organization."
        if self.document_category_id and self.document_category.organization_id != self.organization_id:
            errors["document_category"] = "Document category must belong to this organization."
        if errors:
            raise ValidationError(errors)


class CustomerDocument(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        UNDER_VERIFICATION = "under_verification", "Under verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customer_documents")
    customer = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="documents")
    document_category = models.ForeignKey(DocumentCategory, on_delete=models.PROTECT, related_name="documents")
    document_name = models.CharField(max_length=150)
    file = models.FileField(upload_to=customer_document_upload_path)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=100)
    version = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.UPLOADED)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="uploaded_customer_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_customer_documents")
    verified_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="rejected_customer_documents")
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "customer", "document_category", "version"], name="documents_version_unique"),
            models.UniqueConstraint(fields=["organization", "customer", "document_category"], condition=Q(is_active=True), name="documents_one_active_version"),
        ]
        indexes = [models.Index(fields=["organization", "status", "is_active"]), models.Index(fields=["customer", "document_category", "is_active"])]

    def clean(self):
        errors = {}
        if self.customer_id and self.customer.organization_id != self.organization_id:
            errors["customer"] = "Customer must belong to this organization."
        if self.document_category_id and self.document_category.organization_id != self.organization_id:
            errors["document_category"] = "Document category must belong to this organization."
        if errors:
            raise ValidationError(errors)


class CustomerDocumentVerificationHistory(models.Model):
    document = models.ForeignKey(CustomerDocument, on_delete=models.CASCADE, related_name="verification_history")
    old_status = models.CharField(max_length=24, choices=CustomerDocument.Status.choices)
    new_status = models.CharField(max_length=24, choices=CustomerDocument.Status.choices)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="customer_document_status_changes")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Document verification history records are immutable.")
        return super().save(*args, **kwargs)


class EmployeeDocumentCategory(models.Model):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="employee_document_categories")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="employee_document_category_unique")]


class EmployeeDocument(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="employee_documents")
    employee = models.ForeignKey("organizations.OrganizationMembership", on_delete=models.CASCADE, related_name="documents")
    document_category = models.ForeignKey(EmployeeDocumentCategory, on_delete=models.PROTECT, related_name="documents")
    document_name = models.CharField(max_length=150)
    file = models.FileField(upload_to=employee_document_upload_path)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="uploaded_employee_documents")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["organization", "employee", "document_category", "version"], name="employee_document_version_unique"), models.UniqueConstraint(fields=["organization", "employee", "document_category"], condition=Q(is_active=True), name="employee_document_one_active")]
        indexes = [models.Index(fields=["organization", "employee", "is_active"])]

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if self.document_category_id and self.document_category.organization_id != self.organization_id:
            errors["document_category"] = "Document category must belong to this organization."
        if errors:
            raise ValidationError(errors)
