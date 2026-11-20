from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organizations.models import Organization


class OrganizationSettings(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="settings")
    company_name = models.CharField(max_length=150, blank=True)
    company_logo = models.FileField(upload_to="organization_logos/%Y/%m/", null=True, blank=True)
    date_format = models.CharField(max_length=32, default="DD/MM/YYYY")
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    currency = models.CharField(max_length=3, default="INR")
    items_per_page = models.PositiveSmallIntegerField(default=25)
    updated_at = models.DateTimeField(auto_now=True)


class MasterDataCategory(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "code")


class MasterData(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="master_data")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="master_data")
    category = models.ForeignKey(MasterDataCategory, on_delete=models.PROTECT, related_name="items")
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    color = models.CharField(max_length=7, blank=True)
    description = models.TextField(blank=True)
    properties = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("organization", "category", "code"), condition=models.Q(project__isnull=True), name="settings_master_default_code_unique"),
            models.UniqueConstraint(fields=("organization", "project", "category", "code"), condition=models.Q(project__isnull=False), name="settings_master_project_code_unique"),
        ]
        ordering = ("category__code", "sort_order", "name")

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.is_system and (previous.code != self.code or previous.is_system != self.is_system):
                raise ValidationError("System master data key and system flag are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError("System master data can only be deactivated.")
        return super().delete(*args, **kwargs)


class IntegrationConfiguration(models.Model):
    class Type(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        DOCUMENT_STORAGE = "document_storage", "Document storage"
        META_ADS = "meta_ads", "Meta Ads"
        GOOGLE_ADS = "google_ads", "Google Ads"
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
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=("organization", "integration_type", "name"), name="settings_integration_unique")]


class SystemParameter(models.Model):
    class DataType(models.TextChoices):
        STRING = "string", "String"; INTEGER = "integer", "Integer"; DECIMAL = "decimal", "Decimal"; BOOLEAN = "boolean", "Boolean"; JSON = "json", "JSON"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="system_parameters")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="system_parameters")
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
            models.UniqueConstraint(fields=("organization", "parameter_key"), condition=models.Q(project__isnull=True), name="settings_parameter_default_key_unique"),
            models.UniqueConstraint(fields=("organization", "project", "parameter_key"), condition=models.Q(project__isnull=False), name="settings_parameter_project_key_unique"),
        ]


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        # Django's SET_NULL collector path is the only permitted bulk update.
        # Payload, action, actor and other audit content are immutable.
        if set(kwargs) <= {"organization", "organization_id", "project", "project_id"} and all(value is None for value in kwargs.values()):
            return super().update(**kwargs)
        raise ValidationError("Audit logs are immutable and cannot be updated.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit logs are immutable and cannot be deleted.")


class AuditLog(models.Model):
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="settings_audit_logs")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="settings_audit_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="settings_audit_logs")
    module = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    method = models.CharField(max_length=16, blank=True)
    route = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    payload_before = models.JSONField(null=True, blank=True)
    payload_after = models.JSONField(null=True, blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    objects = AuditLogQuerySet.as_manager()
    class Meta:
        ordering = ("-created_at", "-id")
    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit logs are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit logs are immutable and cannot be deleted.")


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
