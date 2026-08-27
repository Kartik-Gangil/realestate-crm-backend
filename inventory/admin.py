from django.contrib import admin

from .models import Agreement, Block, Installment, InstallmentPayment, Payment, PaymentRefund, Plot, PlotBooking, PlotHold, PlotSelection, PlotStatusHistory, Possession, RecentlyViewedPlot, Registry


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "created_at")
    list_filter = ("organization",)
    search_fields = ("name", "code", "organization__name")
    list_select_related = ("organization",)
    ordering = ("name",)


@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = (
        "plot_number", "block", "organization", "status", "size",
        "plot_type", "rate_per_sq_unit", "total_price",
    )
    list_filter = ("organization", "block", "status", "plot_type")
    search_fields = ("plot_number", "block__name", "block__code")
    list_select_related = ("organization", "block", "created_by")
    autocomplete_fields = ("organization", "block", "created_by")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("block__name", "plot_number")


@admin.register(PlotStatusHistory)
class PlotStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("plot", "old_status", "new_status", "changed_by", "changed_at", "reason")
    list_filter = ("old_status", "new_status", "changed_at")
    search_fields = ("plot__plot_number", "reason", "changed_by__email")
    list_select_related = ("plot", "changed_by")
    readonly_fields = ("plot", "old_status", "new_status", "reason", "changed_by", "changed_at")
    ordering = ("-changed_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlotHold)
class PlotHoldAdmin(admin.ModelAdmin):
    list_display = ("plot", "action_type", "from_datetime", "to_datetime", "created_by", "created_at", "released_at")
    list_filter = ("action_type", "released_at")
    search_fields = ("plot__plot_number", "reason", "notes", "created_by__email")
    list_select_related = ("plot", "created_by")
    readonly_fields = ("created_at",)
    ordering = ("-created_at", "-id")


@admin.register(PlotBooking)
class PlotBookingAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "plot", "status", "site_visit", "created_by", "created_at")
    list_filter = ("organization", "status", "created_at")
    search_fields = ("lead__first_name", "lead__last_name", "lead__phone", "plot__plot_number")
    list_select_related = ("organization", "lead", "plot", "site_visit", "created_by")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("organization", "lead", "plot", "created_by")
    ordering = ("-created_at", "-id")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "amount", "payment_method", "status", "payment_date", "received_by")
    list_filter = ("organization", "status", "payment_method")
    search_fields = ("transaction_reference", "booking__plot__plot_number", "booking__lead__phone")
    list_select_related = ("organization", "booking", "received_by")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status not in {Payment.Status.SUCCESS, Payment.Status.REFUNDED}


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "amount", "refund_date", "processed_by")
    list_select_related = ("payment", "processed_by")
    readonly_fields = ("payment", "amount", "reason", "refund_date", "processed_by", "created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ("booking", "installment_number", "title", "amount", "due_date", "status")
    list_filter = ("organization", "status")
    list_select_related = ("organization", "booking")


@admin.register(InstallmentPayment)
class InstallmentPaymentAdmin(admin.ModelAdmin):
    list_display = ("installment", "payment", "amount", "created_at")
    list_select_related = ("installment", "payment")
    readonly_fields = ("installment", "payment", "amount", "created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Agreement, Registry, Possession)
class SalesLegalAdmin(admin.ModelAdmin):
    list_display = ("booking", "status", "created_at")
    list_filter = ("organization", "status")
    list_select_related = ("organization", "booking")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PlotSelection)
class PlotSelectionAdmin(admin.ModelAdmin):
    list_display = ("id", "plot", "lead", "site_visit", "selected_by", "status", "selected_at", "expires_at")
    list_filter = ("organization", "status", "selected_at")
    search_fields = ("plot__plot_number", "lead__first_name", "lead__last_name")
    list_select_related = ("organization", "plot", "lead", "site_visit", "selected_by")
    readonly_fields = ("selected_at", "created_at", "updated_at", "released_at")
    def has_delete_permission(self, request, obj=None): return False


@admin.register(RecentlyViewedPlot)
class RecentlyViewedPlotAdmin(admin.ModelAdmin):
    list_display = ("plot", "user", "organization", "viewed_at")
    list_select_related = ("plot", "user", "organization")
    readonly_fields = ("plot", "user", "organization", "viewed_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False