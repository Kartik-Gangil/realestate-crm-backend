from django.contrib import admin

from .models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "project", "is_active", "created_at", "updated_at")
    list_filter = ("organization", "project", "is_active")
    search_fields = ("name", "description", "organization__name", "project__name")
    list_select_related = ("organization", "project")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_id", "submitted_by", "category", "amount", "status", "payment_status", "date")
    list_filter = ("organization", "project", "status", "payment_status", "date")
    search_fields = ("expense_id", "description", "submitted_by__email")
    list_select_related = ("organization", "project", "category", "submitted_by")
