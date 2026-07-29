from django.contrib import admin

from .models import Organization, OrganizationMembership, PlatformOrganizationAccess


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_by", "created_at")
    search_fields = ("name", "slug")
    inlines = (OrganizationMembershipInline,)


@admin.register(PlatformOrganizationAccess)
class PlatformOrganizationAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "granted_by", "created_at")
    list_select_related = ("user", "organization", "granted_by")