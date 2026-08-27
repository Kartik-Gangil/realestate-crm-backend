from django.contrib import admin

from .models import (AttendanceRecord, LeaveRequest, Organization, OrganizationHoliday, OrganizationMembership,
                     OrganizationRole, Permission, PlatformOrganizationAccess)


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


@admin.register(OrganizationRole)
class OrganizationRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_system")
    list_filter = ("organization", "is_system")
    search_fields = ("name", "code")
    filter_horizontal = ("permissions",)


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("id","module", "action", "name")
    list_filter = ("module",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("employee", "attendance_date", "check_in", "check_out", "total_hours", "status")
    list_filter = ("organization", "status", "attendance_date")
    list_select_related = ("employee", "organization")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "from_date", "to_date", "days", "status", "approved_by")
    list_filter = ("organization", "leave_type", "status")
    list_select_related = ("employee", "organization", "approved_by")


@admin.register(OrganizationHoliday)
class OrganizationHolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "holiday_date", "organization", "source")
    list_filter = ("organization", "source")
