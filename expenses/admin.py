from django.contrib import admin

from .models import ActivityLog, ApprovalStep, Expense, ExpenseCategory, Payment, ReimbursementRequest


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active", "created_at")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "description")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_id", "organization", "amount", "category", "status", "payment_status", "date", "is_deleted")
    list_filter = ("organization", "status", "payment_status", "is_deleted", "is_advance", "category")
    search_fields = ("description", "notes", "project_reference", "paid_by__email", "submitted_by__email")
    list_select_related = ("organization", "category", "paid_by", "submitted_by")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("expense", "step_name", "status", "actor", "acted_at")
    list_filter = ("status", "step_name")
    readonly_fields = ("expense", "step_name", "actor", "status", "acted_at", "comment")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("expense", "payment_status", "payment_date", "paid_amount", "paid_by")
    list_filter = ("payment_status", "payment_date")


@admin.register(ReimbursementRequest)
class ReimbursementRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "expense", "amount", "status", "requested_on", "resolved_on")
    list_filter = ("status", "requested_on")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("expense", "action", "actor", "action_date")
    list_filter = ("action", "action_date")
    readonly_fields = ("expense", "action", "actor", "action_date", "snapshot")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
