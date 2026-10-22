from rest_framework import serializers

from core.files import DOCUMENT_KINDS, validate_upload
from .models import MAX_RECEIPT_SIZE, Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ("id", "name", "description", "is_active", "project", "created_at", "updated_at")
        read_only_fields = ("id", "project", "created_at", "updated_at")

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Category name is required.")
        return value


class ExpenseSerializer(serializers.ModelSerializer):
    submitted_by = serializers.SerializerMethodField()
    category = ExpenseCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(source="category", queryset=ExpenseCategory.objects.all(), write_only=True)

    class Meta:
        model = Expense
        fields = (
            "id", "expense_id", "date", "category", "category_id", "amount", "description", "notes",
            "project_reference", "payment_method", "paid_by", "is_advance", "receipt", "status",
            "payment_status", "submitted_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "expense_id", "category", "status", "payment_status", "submitted_by", "created_at", "updated_at")

    def get_submitted_by(self, obj):
        return {"id": obj.submitted_by_id, "name": obj.submitted_by.get_full_name() or obj.submitted_by.email}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["receipt"] = f"/api/expenses/{instance.pk}/receipt/" if instance.receipt else None
        return data

    def validate_receipt(self, value):
        if value:
            validate_upload(value, kinds=DOCUMENT_KINDS, max_bytes=MAX_RECEIPT_SIZE, field=None)
        return value

    def validate(self, attrs):
        action = self.context.get("action", "draft")
        amount = attrs.get("amount", getattr(self.instance, "amount", 0))
        receipt = attrs.get("receipt", getattr(self.instance, "receipt", None))
        if action == "submit" and amount > 5000 and not receipt:
            raise serializers.ValidationError({"receipt": "A receipt is required for expenses above ₹5,000."})
        return attrs
