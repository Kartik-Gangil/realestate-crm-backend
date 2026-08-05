from django.contrib import admin

from .models import FollowUpCall, Lead


class FollowUpCallInline(admin.TabularInline):
    model = FollowUpCall
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "organization", "phone", "source", "assigned_membership", "created_at")
    list_filter = ("organization", "source", "assigned_membership")
    search_fields = ("first_name", "last_name", "email", "phone")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("organization", "assigned_membership__user")
    inlines = (FollowUpCallInline,)


@admin.register(FollowUpCall)
class FollowUpCallAdmin(admin.ModelAdmin):
    list_display = ("lead", "organization", "telecaller_membership", "status", "outcome", "next_follow_up", "called_at")
    list_filter = ("organization", "status", "outcome", "telecaller_membership")
    search_fields = ("lead__first_name", "lead__last_name", "lead__phone", "note")
    list_select_related = ("organization", "lead", "telecaller_membership__user")