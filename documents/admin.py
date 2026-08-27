from django.contrib import admin
from .models import (CustomerDocument, CustomerDocumentRequirement, CustomerDocumentVerificationHistory,
                     DocumentCategory, EmployeeDocument, EmployeeDocumentCategory)

@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "code")
    list_select_related = ("organization",)

@admin.register(CustomerDocumentRequirement)
class RequirementAdmin(admin.ModelAdmin):
    list_display = ("customer", "document_category", "organization", "is_mandatory", "is_active")
    list_filter = ("organization", "is_mandatory", "is_active")
    list_select_related = ("customer", "document_category", "organization")

@admin.register(CustomerDocument)
class CustomerDocumentAdmin(admin.ModelAdmin):
    list_display = ("customer", "document_category", "document_name", "version", "status", "uploaded_at", "expiry_date", "is_active", "uploaded_by", "verified_by")
    list_filter = ("organization", "document_category", "status", "is_active", "expiry_date")
    search_fields = ("customer__first_name", "customer__last_name", "document_name", "file_name")
    list_select_related = ("customer", "document_category", "organization", "uploaded_by", "verified_by")
    readonly_fields = ("version", "file_name", "file_size", "content_type", "uploaded_at", "verified_at", "rejected_at", "archived_at", "created_at", "updated_at")

@admin.register(CustomerDocumentVerificationHistory)
class DocumentHistoryAdmin(admin.ModelAdmin):
    list_display = ("document", "old_status", "new_status", "changed_by", "changed_at")
    readonly_fields = ("document", "old_status", "new_status", "reason", "changed_by", "changed_at")
    list_select_related = ("document", "changed_by")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

@admin.register(EmployeeDocumentCategory)
class EmployeeDocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "code")

@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ("employee", "document_category", "document_name", "version", "status", "uploaded_at", "is_active")
    list_filter = ("organization", "document_category", "status", "is_active")
    search_fields = ("employee__employee_id", "document_name", "file_name")
    list_select_related = ("employee", "document_category", "organization", "uploaded_by")
    readonly_fields = ("version", "file_name", "file_size", "content_type", "uploaded_at", "archived_at", "created_at", "updated_at")
