from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from core.audit_context import reset_audit_signal_suppression, suppress_audit_signals
from system_settings.audit import log_bulk_audit

from .security import is_developer


User = get_user_model()

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Keep Developer markers out of Django's editable user surface."""

    def has_change_permission(self, request, obj=None):
        if obj is not None and is_developer(obj):
            return False
        if obj is not None and (obj.is_superuser or obj.groups.filter(name="Platform Admin").exists()):
            return bool(is_developer(request.user) or request.user.is_superuser)
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and is_developer(obj):
            return False
        if obj is not None and (obj.is_superuser or obj.groups.filter(name="Platform Admin").exists()):
            return bool(is_developer(request.user) or request.user.is_superuser)
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and is_developer(obj):
            return tuple(dict.fromkeys((*fields, "username", "email", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")))
        return fields

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_queryset(self, request, queryset):
        victims = list(queryset.exclude(developer_account__isnull=False))
        if not victims:
            return
        token = suppress_audit_signals()
        try:
            User.objects.filter(pk__in=[user.pk for user in victims]).delete()
        finally:
            reset_audit_signal_suppression(token)
        log_bulk_audit(
            request=request,
            module="users",
            action="bulk_delete",
            instances=victims,
            record_ids=[user.pk for user in victims],
            changed_values={"deleted": True},
        )
