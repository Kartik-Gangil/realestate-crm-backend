from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.files import DOCUMENT_KINDS, validate_upload
from .models import MAX_RECEIPT_SIZE, Expense, ExpenseCategory


def user_to_dict(user):
    if not user:
        return None
    return {"id": user.id, "email": user.email, "name": user.get_full_name() or user.get_username()}


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
    paid_by = serializers.SerializerMethodField()
    reimbursed_by = serializers.SerializerMethodField()
    paid_by_id = serializers.PrimaryKeyRelatedField(
        source="paid_by", queryset=get_user_model().objects.all(), write_only=True, required=False
    )
    category = ExpenseCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=ExpenseCategory.objects.all(), write_only=True
    )
    approval_steps = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = (
            "id", "expense_id", "date", "category", "category_id", "amount", "description", "notes",
            "project_reference", "payment_method", "paid_by", "paid_by_id", "is_advance", "receipt", "status",
            "payment_status", "rejection_reason", "is_deleted", "submitted_by", "approval_steps", "activity",
            "reimbursement_reference", "reimbursed_by", "reimbursed_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "expense_id", "category", "status", "payment_status", "rejection_reason", "is_deleted",
            "submitted_by", "approval_steps", "activity", "reimbursed_by", "reimbursed_at", "created_at", "updated_at",
        )

    def get_submitted_by(self, obj):
        return user_to_dict(obj.submitted_by)

    def get_paid_by(self, obj):
        return user_to_dict(obj.paid_by)

    def get_reimbursed_by(self, obj):
        return user_to_dict(obj.reimbursed_by)

    def get_approval_steps(self, obj):
        return [
            {
                "id": step.id,
                "step_name": step.step_name,
                "actor": user_to_dict(step.actor),
                "status": step.status,
                "acted_at": step.acted_at.isoformat() if step.acted_at else None,
                "comment": step.comment,
            }
            for step in obj.approval_steps.all()
        ]

    def get_activity(self, obj):
        return [
            {
                "id": item.id,
                "action": item.action,
                "actor": user_to_dict(item.actor),
                "action_date": item.action_date.isoformat(),
                "snapshot": item.snapshot,
                "details": item.details,
            }
            for item in obj.activity_logs.all()
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["receipt"] = f"/api/expenses/{instance.pk}/receipt/" if instance.receipt else None
        return data

    def validate_receipt(self, value):
        if value:
            validate_upload(value, kinds=DOCUMENT_KINDS, max_bytes=MAX_RECEIPT_SIZE, field=None)
        return value

