from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organizations.models import Organization, ProjectScopedModel
from organizations.project_scope import get_current_project_id


class OrganizationSettings(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="settings")
    company_name = models.CharField(max_length=150, blank=True)
    company_logo = models.FileField(upload_to="organization_logos/%Y/%m/", null=True, blank=True)
    date_format = models.CharField(max_length=32, default="DD/MM/YYYY")
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    currency = models.CharField(max_length=3, default="INR")
    items_per_page = models.PositiveSmallIntegerField(default=25)
    updated_at = models.DateTimeField(auto_now=True)


class MasterDataCategory(ProjectScopedModel):
    """FR-P2-01 / DM-P2-01: project-scoped master-data category."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="master_data_categories"
    )
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "project", "code"),
                name="settings_master_category_code_unique",
            ),
            models.UniqueConstraint(
                fields=("organization", "code"),
                condition=models.Q(project__isnull=True),
                name="settings_master_category_code_legacy",
            ),
        ]

    def __str__(self):
        return self.name


class MasterData(ProjectScopedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="master_data")
    category = models.ForeignKey(
        MasterDataCategory,
        on_delete=models.PROTECT,
        related_name="items",
    )
    master_type = models.CharField(max_length=40)
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    color = models.CharField(max_length=7, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "project", "master_type", "code"), name="settings_master_code_unique"),
            models.UniqueConstraint(fields=("organization", "master_type", "code"), condition=models.Q(project__isnull=True), name="settings_master_code_legacy"),
        ]
        ordering = ("master_type", "sort_order", "name")

    def save(self, *args, **kwargs):
        project_id = self.project_id or get_current_project_id()
        if not self.category_id and self.organization_id and self.master_type:
            self.category, _ = MasterDataCategory.objects.get_or_create(
                organization_id=self.organization_id,
                project_id=project_id,
                code=self.master_type,
                defaults={"name": self.master_type.replace("_", " ").title()},
            )
        elif self.category_id:
            self.master_type = self.category.code
        return super().save(*args, **kwargs)


class IntegrationConfiguration(ProjectScopedModel):
    class Type(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        DOCUMENT_STORAGE = "document_storage", "Document storage"
    class Status(models.TextChoices):
        NOT_CONFIGURED = "not_configured", "Not configured"
        CONFIGURED = "configured", "Configured"
        CONNECTED = "connected", "Connected"
        DISCONNECTED = "disconnected", "Disconnected"
        ERROR = "error", "Error"
        DISABLED = "disabled", "Disabled"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="integrations")
    integration_type = models.CharField(max_length=32, choices=Type.choices)
    name = models.CharField(max_length=120)
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_CONFIGURED)
    configuration = models.JSONField(default=dict, blank=True)
    encrypted_secrets = models.TextField(blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "project", "integration_type", "name"), name="settings_integration_unique"),
            models.UniqueConstraint(fields=("organization", "integration_type", "name"), condition=models.Q(project__isnull=True), name="settings_integration_legacy"),
        ]


class SystemParameter(ProjectScopedModel):
    class DataType(models.TextChoices):
        STRING = "string", "String"; INTEGER = "integer", "Integer"; FLOAT = "float", "Float"; DECIMAL = "decimal", "Decimal"; BOOLEAN = "boolean", "Boolean"; JSON = "json", "JSON"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="system_parameters")
    category = models.CharField(max_length=40, default="general")
    parameter_key = models.SlugField(max_length=100)
    parameter_name = models.CharField(max_length=150)
    value = models.JSONField()
    data_type = models.CharField(max_length=16, choices=DataType.choices)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_critical = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "project", "parameter_key"), name="settings_parameter_key_unique"),
            models.UniqueConstraint(fields=("organization", "parameter_key"), condition=models.Q(project__isnull=True), name="settings_parameter_key_legacy"),
        ]


class AuditLog(ProjectScopedModel):
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="settings_audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="settings_audit_logs")
    module = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    class Meta:
        ordering = ("-timestamp", "-id")
    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit logs are immutable.")
        return super().save(*args, **kwargs)


class BackupRecord(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"; FAILED = "failed", "Failed"; UNSUPPORTED = "unsupported", "Unsupported"; RUNNING = "running", "Running"
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    storage_location_reference = models.CharField(max_length=255, blank=True)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="initiated_backups")
    error_message_safe = models.CharField(max_length=500, blank=True)
