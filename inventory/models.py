from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta


def default_selection_expiry():
    return timezone.now() + timedelta(minutes=30)


class Block(models.Model):
    """Top-level inventory grouping, scoped only to the organization."""

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="inventory_blocks"
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="unique_inventory_block_code"
            ),
        ]

    def __str__(self):
        return f"{self.organization} - {self.name}"


class Plot(models.Model):
    class PlotType(models.TextChoices):
        RESIDENTIAL = "residential", "Residential"
        COMMERCIAL = "commercial", "Commercial"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BLOCKED = "blocked", "Blocked"
        HOLD = "hold", "Hold"
        BOOKED = "booked", "Booked"
        SOLD = "sold", "Sold"
        CANCELLED = "cancelled", "Cancelled"
        UNDER_CONSTRUCTION = "under_construction", "Under Construction"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="plots"
    )
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="plots")
    plot_number = models.CharField(max_length=50)
    size = models.DecimalField(max_digits=12, decimal_places=2)
    plot_type = models.CharField(max_length=20, choices=PlotType.choices, default=PlotType.RESIDENTIAL)
    rate_per_sq_unit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    total_price = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    facing = models.CharField(max_length=50, blank=True)
    dimensions = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.AVAILABLE)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_plots",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["block__name", "plot_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "block", "plot_number"],
                name="unique_inventory_plot_number",
            ),
            models.CheckConstraint(condition=Q(size__gt=0), name="inventory_plot_size_positive"),
            models.CheckConstraint(
                condition=Q(rate_per_sq_unit__isnull=True) | Q(rate_per_sq_unit__gt=0),
                name="inventory_plot_rate_positive",
            ),
            models.CheckConstraint(
                condition=Q(total_price__isnull=True) | Q(total_price__gt=0),
                name="inventory_plot_total_price_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "block"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.block_id and self.organization_id != self.block.organization_id:
            errors["block"] = "Block must belong to this organization."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.block} / {self.plot_number}"


class PlotStatusHistory(models.Model):
    """Immutable audit event for a plot status transition."""

    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=24, choices=Plot.Status.choices)
    new_status = models.CharField(max_length=24, choices=Plot.Status.choices)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="plot_status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]
        indexes = [models.Index(fields=["plot", "-changed_at"])]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Plot status history records are immutable.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.plot}: {self.old_status} → {self.new_status}"


class PlotHold(models.Model):
    class ActionType(models.TextChoices):
        BLOCK = "block", "Block"
        HOLD = "hold", "Hold"

    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="hold_records")
    action_type = models.CharField(max_length=10, choices=ActionType.choices)
    reason = models.TextField()
    from_datetime = models.DateTimeField(null=True, blank=True)
    to_datetime = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_plot_holds",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["plot", "released_at"]),
            models.Index(fields=["plot", "from_datetime", "to_datetime"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(from_datetime__isnull=True)
                    | Q(to_datetime__isnull=True)
                    | Q(to_datetime__gt=models.F("from_datetime"))
                ),
                name="inventory_hold_time_range_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.from_datetime and self.to_datetime and self.to_datetime <= self.from_datetime:
            raise ValidationError({"to_datetime": "Must be later than from_datetime."})

    def __str__(self):
        return f"{self.plot} - {self.get_action_type_display()}"


class PlotBooking(models.Model):
    """A lead's booking intent; plot state remains owned by inventory services."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="plot_bookings"
    )
    lead = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="plot_bookings")
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="bookings")
    site_visit = models.ForeignKey(
        "leads.Sitevisit", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="plot_bookings",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    final_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_plot_bookings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "lead", "created_at"]),
            models.Index(fields=["organization", "plot", "status"]),
            models.Index(fields=["site_visit"]),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.lead_id and self.lead.organization_id != self.organization_id:
            errors["lead"] = "Lead must belong to this organization."
        if self.plot_id and self.plot.organization_id != self.organization_id:
            errors["plot"] = "Plot must belong to this organization."
        if self.site_visit_id:
            if self.site_visit.organization_id != self.organization_id:
                errors["site_visit"] = "Site visit must belong to this organization."
            elif self.lead_id and self.site_visit.lead_id != self.lead_id:
                errors["site_visit"] = "Site visit must belong to the selected lead."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Booking #{self.pk or 'new'}: {self.plot} for {self.lead}"


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        UPI = "upi", "UPI"
        CHEQUE = "cheque", "Cheque"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="payments")
    # Kept for compatibility with the original booking-payment APIs.  New
    # payments use PaymentAllocation and may cover more than one booking.
    booking = models.ForeignKey(PlotBooking, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    payment_id = models.CharField(max_length=40, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    transaction_reference = models.CharField(max_length=100, blank=True)
    payment_date = models.DateField()
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="received_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_payment_amount_positive"), models.UniqueConstraint(fields=["organization", "payment_id"], name="inventory_payment_org_payment_id_unique")]
        indexes = [models.Index(fields=["organization", "booking", "status"]), models.Index(fields=["organization", "payment_date"]), models.Index(fields=["organization", "transaction_reference"])]

    def clean(self):
        if self.booking_id and self.organization_id != self.booking.organization_id:
            raise ValidationError({"booking": "Booking must belong to this organization."})


class PaymentRefund(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="payment_refunds", null=True, blank=True)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="refunds")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.TextField()
    refund_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_payment_refunds")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_payment_refunds")
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="processed_payment_refunds")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-refund_date", "-id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_refund_amount_positive")]


class PaymentAllocation(models.Model):
    """An immutable financial application of a payment to a real due."""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="payment_allocations")
    booking = models.ForeignKey(PlotBooking, on_delete=models.PROTECT, related_name="payment_allocations")
    installment = models.ForeignKey("Installment", null=True, blank=True, on_delete=models.PROTECT, related_name="payment_allocations")
    registry_charge = models.ForeignKey("RegistryCharge", null=True, blank=True, on_delete=models.PROTECT, related_name="payment_allocations")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_payment_allocation_positive")]
        indexes = [models.Index(fields=["booking", "payment"]), models.Index(fields=["installment"]), models.Index(fields=["registry_charge"])]

    def clean(self):
        errors = {}
        if self.payment_id and self.booking_id and self.payment.organization_id != self.booking.organization_id:
            errors["booking"] = "Booking must belong to the payment organization."
        if self.installment_id and self.installment.booking_id != self.booking_id:
            errors["installment"] = "Installment must belong to the selected booking."
        if self.registry_charge_id and self.registry_charge.registry.booking_id != self.booking_id:
            errors["registry_charge"] = "Registry charge must belong to the selected booking."
        if self.installment_id and self.registry_charge_id:
            errors["allocation"] = "Allocate to either an installment or a registry charge."
        if errors:
            raise ValidationError(errors)


class PaymentReceipt(models.Model):
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="receipt")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="payment_receipts")
    receipt_number = models.CharField(max_length=48)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "receipt_number"], name="inventory_receipt_org_number_unique")]


class PaymentStatusHistory(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=16, blank=True)
    new_status = models.CharField(max_length=16)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payment_status_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-changed_at", "-id"]
    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists(): raise ValidationError("Payment status history records are immutable.")
        return super().save(*args, **kwargs)


class PaymentAdjustment(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="adjustments")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="payment_adjustments")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_payment_adjustment_positive")]


class Installment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="installments")
    booking = models.ForeignKey(PlotBooking, on_delete=models.CASCADE, related_name="installments")
    installment_number = models.PositiveIntegerField()
    title = models.CharField(max_length=150)
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["booking", "installment_number"]
        constraints = [models.UniqueConstraint(fields=["booking", "installment_number"], name="unique_booking_installment_number"), models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_installment_amount_positive")]
        indexes = [models.Index(fields=["organization", "booking", "status"]), models.Index(fields=["organization", "due_date"])]

    def clean(self):
        if self.booking_id and self.organization_id != self.booking.organization_id:
            raise ValidationError({"booking": "Booking must belong to this organization."})


class InstallmentPayment(models.Model):
    installment = models.ForeignKey(Installment, on_delete=models.CASCADE, related_name="allocations")
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="inventory_allocation_amount_positive")]
        indexes = [models.Index(fields=["payment", "installment"])]

    def clean(self):
        if self.payment_id and self.installment_id and self.payment.booking_id != self.installment.booking_id:
            raise ValidationError({"installment": "Payment and installment must belong to the same booking."})


class Agreement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        SIGNED = "signed", "Signed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="agreements")
    booking = models.OneToOneField(PlotBooking, on_delete=models.CASCADE, related_name="agreement")
    agreement_number = models.CharField(max_length=100, blank=True)
    agreement_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    document_reference = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_agreements")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"]), models.Index(fields=["organization", "agreement_number"])]

    def clean(self):
        if self.booking_id and self.organization_id != self.booking.organization_id:
            raise ValidationError({"booking": "Booking must belong to this organization."})


class Registry(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROCESS = "in_process", "In process"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="registries")
    booking = models.OneToOneField(PlotBooking, on_delete=models.CASCADE, related_name="registry")
    registry_number = models.CharField(max_length=100, blank=True)
    registry_date = models.DateField(null=True, blank=True)
    registry_time = models.TimeField(null=True, blank=True)
    sub_registrar_office = models.CharField(max_length=200, blank=True)
    document_type = models.CharField(max_length=100, blank=True)
    consideration_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    agreement_number = models.CharField(max_length=100, blank=True)
    agreement_date = models.DateField(null=True, blank=True)
    reminder_date = models.DateField(null=True, blank=True)
    reminder_enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_registries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"]), models.Index(fields=["organization", "registry_number"])]

    def clean(self):
        if self.booking_id and self.organization_id != self.booking.organization_id:
            raise ValidationError({"booking": "Booking must belong to this organization."})


class RegistryCharge(models.Model):
    registry = models.ForeignKey(Registry, on_delete=models.CASCADE, related_name="charges")
    code = models.SlugField(max_length=64)
    label = models.CharField(max_length=120)
    calculation_type = models.CharField(max_length=16, default="fixed")
    calculation_value = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["registry", "code"], name="inventory_registry_charge_unique"), models.CheckConstraint(condition=Q(amount__gte=0), name="inventory_registry_charge_nonnegative")]


class RegistryStatusHistory(models.Model):
    registry = models.ForeignKey(Registry, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=16, blank=True)
    new_status = models.CharField(max_length=16)
    remarks = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="registry_status_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-changed_at", "-id"]
    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists(): raise ValidationError("Registry status history records are immutable.")
        return super().save(*args, **kwargs)


class Possession(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="possessions")
    booking = models.OneToOneField(PlotBooking, on_delete=models.CASCADE, related_name="possession")
    possession_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    handed_over_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handed_over_possessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"]), models.Index(fields=["organization", "possession_date"])]

    def clean(self):
        if self.booking_id and self.organization_id != self.booking.organization_id:
            raise ValidationError({"booking": "Booking must belong to this organization."})


class PlotSelection(models.Model):
    """Temporary executive selection. It deliberately does not change plot status."""
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CONFIRMED = "confirmed", "Confirmed"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="plot_selections")
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="selections")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="plot_selections")
    site_visit = models.ForeignKey("leads.Sitevisit", null=True, blank=True, on_delete=models.SET_NULL, related_name="plot_selections")
    selected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="plot_selections")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    selected_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_selection_expiry)
    released_at = models.DateTimeField(null=True, blank=True)
    released_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-selected_at", "-id"]
        indexes = [models.Index(fields=["organization", "plot", "status"]), models.Index(fields=["organization", "status", "expires_at"])]

    def clean(self):
        errors = {}
        if self.plot_id and self.plot.organization_id != self.organization_id: errors["plot"] = "Plot must belong to this organization."
        if self.lead_id and self.lead.organization_id != self.organization_id: errors["lead"] = "Lead must belong to this organization."
        if self.site_visit_id:
            if self.site_visit.organization_id != self.organization_id: errors["site_visit"] = "Site visit must belong to this organization."
            elif self.lead_id and self.site_visit.lead_id != self.lead_id: errors["site_visit"] = "Site visit must belong to the selected lead."
        if errors: raise ValidationError(errors)


class RecentlyViewedPlot(models.Model):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user", "plot"], name="unique_recently_viewed_plot")]
        indexes = [models.Index(fields=["organization", "user", "-viewed_at"])]
