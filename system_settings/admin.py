from django.contrib import admin
from .models import AuditLog, BackupRecord, IntegrationConfiguration, MasterData, OrganizationSettings, SystemParameter
from users.security import is_developer

admin.site.register((OrganizationSettings, MasterData, IntegrationConfiguration, SystemParameter, BackupRecord))
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    readonly_fields = ("organization", "project", "user", "module", "action", "method", "route", "created_at", "ip_address", "details", "payload_before", "payload_after", "target_type", "target_id")
    list_display = ("created_at", "module", "action", "organization", "user")
    def has_module_permission(self, request):
        return bool(request.user and request.user.is_authenticated and is_developer(request.user))
    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_authenticated and is_developer(request.user))
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
