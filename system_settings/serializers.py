import json
import math
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rest_framework import serializers
from .models import AuditLog, BackupRecord, IntegrationConfiguration, MasterData, OrganizationSettings, SystemParameter


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = ("company_name", "company_logo", "date_format", "timezone", "currency", "items_per_page", "updated_at")
        read_only_fields = ("updated_at",)
    def validate_timezone(self, value):
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise serializers.ValidationError("Use a valid IANA timezone.")
        return value
    def validate_currency(self, value):
        if not value.isalpha() or len(value) != 3: raise serializers.ValidationError("Use a three-letter ISO currency code.")
        return value.upper()
    def validate_items_per_page(self, value):
        if not 1 <= value <= 100: raise serializers.ValidationError("Use a value from 1 to 100.")
        return value


class MasterDataSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()

    class Meta:
        model = MasterData
        fields = ("id", "category", "master_type", "code", "name", "color", "description", "is_active", "is_system", "sort_order", "created_at", "updated_at")
        read_only_fields = ("id", "category", "master_type", "is_system", "created_at", "updated_at")

    def get_category(self, obj):
        return {"id": obj.category_id, "code": obj.category.code, "name": obj.category.name}

    def validate_code(self, value):
        organization = self.context.get("organization")
        project = self.context.get("project")
        master_type = self.context.get("master_type")
        if organization and master_type:
            query = MasterData.objects.filter(
                organization=organization,
                project=project,
                master_type=master_type,
                code=value,
            )
            if self.instance:
                query = query.exclude(pk=self.instance.pk)
            if query.exists():
                raise serializers.ValidationError("An item with this code already exists in the category.")
        return value

    def validate_color(self, value):
        if value and (len(value) != 7 or not value.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in value[1:])):
            raise serializers.ValidationError("Use a #RRGGBB color.")
        return value


class IntegrationSerializer(serializers.ModelSerializer):
    secrets = serializers.JSONField(write_only=True, required=False)
    secrets_configured = serializers.SerializerMethodField()
    class Meta:
        model = IntegrationConfiguration
        fields = ("id", "integration_type", "name", "enabled", "status", "configuration", "secrets", "secrets_configured", "last_tested_at", "last_error", "created_at", "updated_at")
        read_only_fields = ("id", "status", "last_tested_at", "last_error", "created_at", "updated_at")
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
        dtype = attrs.get("data_type", getattr(self.instance, "data_type", None))
        value_supplied = "value" in attrs
        type_changed = "data_type" in attrs
        value = attrs.get("value", getattr(self.instance, "value", None))
        if value is None:
            return attrs
        if value_supplied or type_changed:
            attrs["value"] = self._coerce_value(dtype, value)
        return attrs

    @staticmethod
    def _coerce_value(dtype, value):
        message = f"Value cannot be converted to {dtype}."
        try:
            if dtype == SystemParameter.DataType.STRING:
                if isinstance(value, (dict, list)):
                    raise ValueError
                return str(value)
            if dtype == SystemParameter.DataType.INTEGER:
                if isinstance(value, bool):
                    raise ValueError
                if isinstance(value, int):
                    return value
                if isinstance(value, str):
                    stripped = value.strip()
                    if not stripped or stripped.lstrip("+-").isdigit() is False:
                        raise ValueError
                    return int(stripped)
                raise ValueError
            if dtype == SystemParameter.DataType.FLOAT:
                if isinstance(value, bool):
                    raise ValueError
                converted = float(value)
                if not math.isfinite(converted):
                    raise ValueError
                return converted
            if dtype == SystemParameter.DataType.DECIMAL:
                if isinstance(value, bool):
                    raise ValueError
                converted = Decimal(str(value))
                if not converted.is_finite():
                    raise ValueError
                return format(converted, "f")
            if dtype == SystemParameter.DataType.BOOLEAN:
                if not isinstance(value, bool):
                    raise ValueError
                return value
            if dtype == SystemParameter.DataType.JSON:
                return value
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            raise serializers.ValidationError({"value": message})
        raise serializers.ValidationError({"value": message})


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    class Meta:
        model = AuditLog
        fields = ("id", "organization", "actor", "module", "action", "timestamp", "ip_address", "details", "target_type", "target_id")
    def get_actor(self, o): return {"id": o.actor_id, "email": o.actor.email} if o.actor_id else None
    def get_organization(self, o): return {"id": o.organization_id, "name": o.organization.name, "slug": o.organization.slug} if o.organization_id else None


class BackupRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupRecord
        fields = ("id", "started_at", "completed_at", "status", "size_bytes", "initiated_by", "error_message_safe")
        read_only_fields = fields
