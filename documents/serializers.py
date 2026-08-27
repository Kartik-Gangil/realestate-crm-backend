from rest_framework import serializers

from .models import CustomerDocument, CustomerDocumentRequirement, CustomerDocumentVerificationHistory, DocumentCategory


class DocumentCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentCategory
        fields = ("id", "name", "code", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class DocumentRequirementSerializer(serializers.ModelSerializer):
    category = DocumentCategorySerializer(source="document_category", read_only=True)
    document_category = serializers.PrimaryKeyRelatedField(queryset=DocumentCategory.objects.all())
    class Meta:
        model = CustomerDocumentRequirement
        fields = ("id", "document_category", "category", "is_mandatory", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


def actor(user):
    return {"id": user.id, "email": user.email, "name": user.get_full_name()} if user else None


class CustomerDocumentSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField(); category = DocumentCategorySerializer(source="document_category", read_only=True)
    uploaded_by = serializers.SerializerMethodField(); verified_by = serializers.SerializerMethodField(); rejected_by = serializers.SerializerMethodField()
    class Meta:
        model = CustomerDocument
        fields = ("id", "customer", "document_category", "category", "document_name", "file_name", "file_size", "content_type", "version", "is_active", "status", "expiry_date", "notes", "uploaded_by", "uploaded_at", "verified_by", "verified_at", "rejected_by", "rejected_at", "rejection_reason", "archived_at", "created_at", "updated_at")
    def get_customer(self, obj): return {"id": obj.customer_id, "full_name": obj.customer.full_name, "phone": obj.customer.phone}
    def get_uploaded_by(self, obj): return actor(obj.uploaded_by)
    def get_verified_by(self, obj): return actor(obj.verified_by)
    def get_rejected_by(self, obj): return actor(obj.rejected_by)


class CustomerDocumentUploadSerializer(serializers.Serializer):
    customer = serializers.IntegerField()
    document_category = serializers.IntegerField()
    document_name = serializers.CharField(max_length=150)
    file = serializers.FileField()
    expiry_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class VerificationHistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.SerializerMethodField()
    class Meta:
        model = CustomerDocumentVerificationHistory
        fields = ("id", "old_status", "new_status", "reason", "changed_by", "changed_at")
    def get_changed_by(self, obj): return actor(obj.changed_by)
