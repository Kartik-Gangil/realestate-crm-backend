from django.contrib import admin
from .models import AuditLog, BackupRecord, IntegrationConfiguration, MasterData, MasterDataCategory, OrganizationSettings, SystemParameter

admin.site.register((OrganizationSettings, MasterDataCategory, MasterData, IntegrationConfiguration, SystemParameter, BackupRecord))
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    readonly_fields = ("organization", "actor", "module", "action", "timestamp", "ip_address", "details", "target_type", "target_id")
    list_display = ("timestamp", "module", "action", "organization", "actor")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
