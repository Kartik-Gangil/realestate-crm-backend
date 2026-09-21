import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import get_valid_filename
from organizations.models import ProjectScopedModel


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


class DocumentCategory(ProjectScopedModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="document_categories")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "project", "code"], name="documents_category_org_code_unique"), models.UniqueConstraint(fields=["organization", "code"], condition=Q(project__isnull=True), name="documents_category_org_code_legacy")]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class CustomerDocumentRequirement(ProjectScopedModel):
    # The existing CRM calls the customer entity Lead; APIs retain the customer term.
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customer_document_requirements")
    customer = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="document_requirements")
    document_category = models.ForeignKey(DocumentCategory, on_delete=models.PROTECT, related_name="customer_requirements")
    is_mandatory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "project", "customer", "document_category"], name="documents_requirement_unique"), models.UniqueConstraint(fields=["organization", "customer", "document_category"], condition=Q(project__isnull=True), name="documents_requirement_legacy")]

    def clean(self):
        errors = {}
        if self.customer_id and self.customer.organization_id != self.organization_id:
            errors["customer"] = "Customer must belong to this organization."
        if self.document_category_id and self.document_category.organization_id != self.organization_id:
            errors["document_category"] = "Document category must belong to this organization."
        if errors:
            raise ValidationError(errors)


class CustomerDocument(ProjectScopedModel):
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
            models.UniqueConstraint(fields=["organization", "project", "customer", "document_category", "version"], name="documents_version_unique"),
            models.UniqueConstraint(fields=["organization", "project", "customer", "document_category"], condition=Q(is_active=True), name="documents_one_active_version"),
            models.UniqueConstraint(fields=["organization", "customer", "document_category", "version"], condition=Q(project__isnull=True), name="documents_version_legacy"),
            models.UniqueConstraint(fields=["organization", "customer", "document_category"], condition=Q(project__isnull=True, is_active=True), name="documents_one_active_legacy"),
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


class EkycVerification(ProjectScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="ekyc_verifications")
    customer = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="ekyc_verifications")
    provider = models.CharField(max_length=40, default="mock")
    id_number_encrypted = models.TextField(blank=True)
    verification_status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    response_payload = models.JSONField(default=dict, blank=True)
    face_match_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_ekyc_verifications")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "customer", "verification_status"])]


class DocumentExpiryNotification(ProjectScopedModel):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="document_expiry_notifications")
    document = models.ForeignKey(CustomerDocument, on_delete=models.CASCADE, related_name="expiry_notifications")
    channel = models.CharField(max_length=12, choices=Channel.choices)
    recipient = models.CharField(max_length=255)
    alert_date = models.DateField()
    scheduled_for = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "channel", "alert_date"], name="documents_expiry_notification_unique")]
        indexes = [models.Index(fields=["organization", "status", "scheduled_for"])]


class EmployeeDocumentCategory(ProjectScopedModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="employee_document_categories")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "project", "code"], name="employee_document_category_unique"), models.UniqueConstraint(fields=["organization", "code"], condition=Q(project__isnull=True), name="employee_document_category_legacy")]


class EmployeeDocument(ProjectScopedModel):
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
        constraints = [models.UniqueConstraint(fields=["organization", "project", "employee", "document_category", "version"], name="employee_document_version_unique"), models.UniqueConstraint(fields=["organization", "project", "employee", "document_category"], condition=Q(is_active=True), name="employee_document_one_active"), models.UniqueConstraint(fields=["organization", "employee", "document_category", "version"], condition=Q(project__isnull=True), name="employee_document_version_legacy"), models.UniqueConstraint(fields=["organization", "employee", "document_category"], condition=Q(project__isnull=True, is_active=True), name="employee_document_one_active_legacy")]
        indexes = [models.Index(fields=["organization", "employee", "is_active"])]

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if self.document_category_id and self.document_category.organization_id != self.organization_id:
            errors["document_category"] = "Document category must belong to this organization."
        if errors:
            raise ValidationError(errors)
