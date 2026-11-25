import json
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from rest_framework import serializers
from .models import AuditLog, BackupRecord, IntegrationConfiguration, MasterData, MasterDataCategory, OrganizationSettings, SystemParameter
from .parameters import GENERAL_SETTINGS_CHOICES, PARAMETER_REGISTRY
from .services import parameter_definition, validate_parameter_value
from core.files import validate_image_upload


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    support_email = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    class Meta:
        model = OrganizationSettings
        fields = ("company_name", "company_logo", "support_email", "date_format", "timezone", "currency", "items_per_page", "updated_at")
        read_only_fields = ("updated_at",)
    def validate_company_logo(self, value):
        if value:
            validate_image_upload(value)
        return value

    def validate_support_email(self, value):
        value = value.strip().lower()
        if not value:
            return ""
        if len(value) > 254:
            raise serializers.ValidationError("Enter a valid support email address.")
        try:
            validate_email(value)
        except ValidationError as error:
            raise serializers.ValidationError("Enter a valid support email address.") from error
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        version = int(instance.updated_at.timestamp()) if instance.updated_at else 0
        data["company_logo"] = (f"/api/organizations/{instance.organization.slug}/settings/general/logo/?v={version}"
                                 if instance.company_logo else None)
        data["choices"] = {
            **GENERAL_SETTINGS_CHOICES,
            "timezones": sorted(__import__("zoneinfo").available_timezones()),
        }
        return data
    def validate_timezone(self, value):
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise serializers.ValidationError("Use a valid IANA timezone.")
        return value
    def validate_currency(self, value):
        if value.upper() not in GENERAL_SETTINGS_CHOICES["currencies"]: raise serializers.ValidationError("Use a supported currency code.")
        return value.upper()
    def validate_items_per_page(self, value):
        if value not in GENERAL_SETTINGS_CHOICES["items_per_page"]: raise serializers.ValidationError("Use a supported items-per-page value.")
        return value
    def validate_date_format(self, value):
        if value not in GENERAL_SETTINGS_CHOICES["date_formats"]: raise serializers.ValidationError("Use a supported date format.")
        return value


class MasterDataSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(slug_field="code", queryset=MasterDataCategory.objects.all())
    key = serializers.CharField(source="code", required=False)
    value = serializers.CharField(source="name", required=False)
    color_code = serializers.CharField(source="color", required=False, allow_blank=True)
    class Meta:
        model = MasterData
        fields = ("id", "category", "key", "value", "color_code", "properties", "is_active", "is_system", "sort_order", "created_at", "updated_at")
        read_only_fields = ("id", "is_system", "created_at", "updated_at")
    def validate_color(self, value):
        if value and (len(value) != 7 or not value.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in value[1:])):
            raise serializers.ValidationError("Use a #RRGGBB color.")
        return value

    def validate_color_code(self, value):
        if value and (len(value) != 7 or not value.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in value[1:])):
            raise serializers.ValidationError("Use a #RRGGBB color.")
        return value

    def validate(self, attrs):
        if self.instance and self.instance.is_system:
            category = attrs.get("category", self.instance.category)
            if attrs.get("code", self.instance.code) != self.instance.code or attrs.get("is_system", self.instance.is_system) != self.instance.is_system:
                raise serializers.ValidationError({"key": "System item keys and system flags cannot change."})
            attrs["category"] = self.instance.category
        return attrs


class IntegrationSerializer(serializers.ModelSerializer):
    secrets = serializers.JSONField(write_only=True, required=False)
    secrets_configured = serializers.SerializerMethodField()
    class Meta:
        model = IntegrationConfiguration
        fields = ("id", "integration_type", "name", "enabled", "status", "configuration", "secrets", "secrets_configured", "last_tested_at", "last_synced_at", "last_error", "created_at", "updated_at")
        read_only_fields = ("id", "status", "last_tested_at", "last_synced_at", "last_error", "created_at", "updated_at")
    def get_secrets_configured(self, obj): return bool(obj.encrypted_secrets)
    def validate_configuration(self, value):
        if not isinstance(value, dict): raise serializers.ValidationError("Configuration must be an object.")
        return value


class SystemParameterSerializer(serializers.ModelSerializer):
    confirmation = serializers.BooleanField(write_only=True, required=False)
    class Meta:
        model = SystemParameter
        fields = ("id", "category", "parameter_key", "parameter_name", "value", "data_type", "description", "is_active", "is_critical", "confirmation", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")
    def validate(self, attrs):
        key = attrs.get("parameter_key", getattr(self.instance, "parameter_key", None))
        if key not in PARAMETER_REGISTRY:
            raise serializers.ValidationError({"parameter_key": "Unknown system parameter."})
        definition = parameter_definition(key)
        attrs["data_type"] = definition.data_type
        if self.instance is None:
            attrs.setdefault("parameter_name", definition.name)
        if "value" in attrs:
            attrs["value"] = validate_parameter_value(key, attrs["value"])
        if definition.scope == "organization" and self.context.get("project") is not None:
            raise serializers.ValidationError({"parameter_key": "This parameter is organization-scoped."})
        return attrs


class LegacyMasterDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterData
        fields = ("id", "code", "name", "color", "description", "is_active", "is_system", "sort_order", "created_at", "updated_at")
        read_only_fields = ("id", "is_system", "created_at", "updated_at")


class LegacySystemParameterSerializer(serializers.ModelSerializer):
    confirmation = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = SystemParameter
        fields = ("id", "category", "parameter_key", "parameter_name", "value", "data_type", "description", "is_active", "is_critical", "confirmation", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        data_type = attrs.get("data_type", getattr(self.instance, "data_type", None))
        value = attrs.get("value", getattr(self.instance, "value", None))
        if data_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise serializers.ValidationError({"value": "Value must match integer."})
        return attrs


class AuditLogSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    class Meta:
        model = AuditLog
        fields = ("id", "organization", "project", "user", "module", "action", "method", "route", "created_at", "ip_address", "details", "payload_before", "payload_after", "target_type", "target_id")
    def get_user(self, o): return {"id": o.user_id, "email": o.user.email} if o.user_id else None
    def get_organization(self, o): return {"id": o.organization_id, "name": o.organization.name, "slug": o.organization.slug} if o.organization_id else None


class BackupRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupRecord
        fields = ("id", "started_at", "completed_at", "status", "size_bytes", "initiated_by", "error_message_safe")
        read_only_fields = fields
