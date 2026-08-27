from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Plot, PlotBooking, PlotHold, PlotStatusHistory


STATUS_TRANSITIONS = {
    Plot.Status.AVAILABLE: {Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED, Plot.Status.UNDER_CONSTRUCTION},
    Plot.Status.BLOCKED: {Plot.Status.AVAILABLE, Plot.Status.HOLD},
    Plot.Status.HOLD: {Plot.Status.AVAILABLE, Plot.Status.BOOKED},
    Plot.Status.BOOKED: {Plot.Status.SOLD, Plot.Status.CANCELLED},
    Plot.Status.SOLD: {Plot.Status.CANCELLED},
    Plot.Status.CANCELLED: {Plot.Status.AVAILABLE},
    Plot.Status.UNDER_CONSTRUCTION: {Plot.Status.AVAILABLE, Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.BOOKED},
}
REASON_REQUIRED_FOR = {Plot.Status.BLOCKED, Plot.Status.HOLD, Plot.Status.CANCELLED}

BOOKING_TRANSITIONS = {
    PlotBooking.Status.PENDING: {PlotBooking.Status.CONFIRMED, PlotBooking.Status.CANCELLED},
    PlotBooking.Status.CONFIRMED: {PlotBooking.Status.CANCELLED},
    PlotBooking.Status.CANCELLED: set(),
}


class BookingDocumentValidationError(ValidationError):
    """Carries structured document failures without violating ValidationError's flat dict contract."""
    def __init__(self, document_validation):
        super().__init__({"detail": "Customer documents are incomplete."})
        self.document_validation = document_validation


def validate_booking_transition(old_status, new_status):
    if new_status not in PlotBooking.Status.values:
        raise ValidationError({"status": "Use a valid booking status."})
    if old_status == new_status:
        raise ValidationError({"status": "Booking is already in this status."})
    if new_status not in BOOKING_TRANSITIONS.get(old_status, set()):
        raise ValidationError({"status": f"Cannot change booking status from '{old_status}' to '{new_status}'."})


def _validate_booking_relationships(*, organization, lead, plot, site_visit):
    if lead.organization_id != organization.id:
        raise ValidationError({"lead_id": "Use a lead in this organization."})
    if plot.organization_id != organization.id:
        raise ValidationError({"plot_id": "Use a plot in this organization."})
    if site_visit:
        if site_visit.organization_id != organization.id:
            raise ValidationError({"site_visit_id": "Use a site visit in this organization."})
        if site_visit.lead_id != lead.id:
            raise ValidationError({"site_visit_id": "Site visit must belong to the selected lead."})


def create_plot_booking(*, organization, lead, plot, site_visit, notes, user):
    """Create a pending booking and take the available plot on hold atomically."""
    with transaction.atomic():
        locked_plot = Plot.objects.select_for_update().get(pk=plot.pk, organization=organization)
        _validate_booking_relationships(
            organization=organization, lead=lead, plot=locked_plot, site_visit=site_visit
        )
        if locked_plot.status != Plot.Status.AVAILABLE:
            raise ValidationError({"plot_id": "Only an available plot can be selected for booking."})
        if PlotBooking.objects.filter(
            organization=organization, plot=locked_plot,
            status__in=[PlotBooking.Status.PENDING, PlotBooking.Status.CONFIRMED],
        ).exists():
            raise ValidationError({"plot_id": "This plot already has an active booking."})
        booking = PlotBooking(
            organization=organization, lead=lead, plot=locked_plot, site_visit=site_visit,
            notes=(notes or "").strip(), created_by=user, final_price=locked_plot.total_price,
        )
        booking.full_clean()
        booking.save()
        # This re-locks within the enclosing transaction and remains the only status authority.
        change_plot_status(
            plot=locked_plot, new_status=Plot.Status.HOLD,
            reason="Plot selected for booking", user=user, notes=booking.notes,
        )
        return booking


def confirm_plot_booking(*, booking, user):
    with transaction.atomic():
        locked_booking = PlotBooking.objects.select_for_update().select_related("organization", "lead").get(pk=booking.pk)
        locked_plot = Plot.objects.select_for_update().get(
            pk=locked_booking.plot_id, organization=locked_booking.organization
        )
        validate_booking_transition(locked_booking.status, PlotBooking.Status.CONFIRMED)
        # Import lazily: documents is optional only for migration ordering, not for the rule.
        from documents.services import validate_customer_documents_for_booking
        validation = validate_customer_documents_for_booking(locked_booking.lead)
        if not validation["allowed"]:
            raise BookingDocumentValidationError(validation)
        if locked_plot.status != Plot.Status.HOLD:
            raise ValidationError({"plot": "Only a held plot can have its pending booking confirmed."})
        change_plot_status(
            plot=locked_plot, new_status=Plot.Status.BOOKED,
            reason="Booking confirmed", user=user,
        )
        locked_booking.status = PlotBooking.Status.CONFIRMED
        locked_booking.save(update_fields=["status", "updated_at"])
        return locked_booking


def cancel_plot_booking(*, booking, reason, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "Provide a cancellation reason."})
    with transaction.atomic():
        locked_booking = PlotBooking.objects.select_for_update().select_related("organization").get(pk=booking.pk)
        locked_plot = Plot.objects.select_for_update().get(
            pk=locked_booking.plot_id, organization=locked_booking.organization
        )
        previous_status = locked_booking.status
        validate_booking_transition(previous_status, PlotBooking.Status.CANCELLED)
        if previous_status == PlotBooking.Status.PENDING:
            if locked_plot.status != Plot.Status.HOLD:
                raise ValidationError({"plot": "Pending booking cancellation requires the plot to be on hold."})
            change_plot_status(plot=locked_plot, new_status=Plot.Status.AVAILABLE, reason=reason, user=user)
        else:
            if locked_plot.status != Plot.Status.BOOKED:
                raise ValidationError({"plot": "Confirmed booking cancellation requires the plot to be booked."})
            # Phase 3 permits BOOKED -> CANCELLED -> AVAILABLE; retain both inventory audit events.
            change_plot_status(plot=locked_plot, new_status=Plot.Status.CANCELLED, reason=reason, user=user)
            change_plot_status(plot=locked_plot, new_status=Plot.Status.AVAILABLE, reason=reason, user=user)
        locked_booking.status = PlotBooking.Status.CANCELLED
        locked_booking.cancellation_reason = reason
        locked_booking.save(update_fields=["status", "cancellation_reason", "updated_at"])
        return locked_booking


def validate_status_transition(old_status, new_status):
    if new_status not in Plot.Status.values:
        raise ValidationError({"status": "Use a valid plot status."})
    if old_status == new_status:
        raise ValidationError({"status": "Plot is already in this status."})
    if new_status not in STATUS_TRANSITIONS.get(old_status, set()):
        raise ValidationError({"status": f"Cannot change plot status from '{old_status}' to '{new_status}'."})


def _validate_reason(new_status, reason):
    if new_status in REASON_REQUIRED_FOR and not reason:
        label = Plot.Status(new_status).label.lower()
        raise ValidationError({"reason": f"Reason is required when changing a plot to {label}."})


def _validate_hold_range(from_datetime, to_datetime):
    if from_datetime and to_datetime and to_datetime <= from_datetime:
        raise ValidationError({"to_datetime": "Must be later than from_datetime."})


def _close_active_holds(plot, now):
    plot.hold_records.filter(released_at__isnull=True).update(released_at=now)


def _create_hold_record(plot, new_status, reason, user, from_datetime, to_datetime, notes):
    _validate_hold_range(from_datetime, to_datetime)
    active_holds = plot.hold_records.filter(released_at__isnull=True)
    if from_datetime and to_datetime:
        active_holds = active_holds.filter(
            from_datetime__isnull=False,
            to_datetime__isnull=False,
            from_datetime__lt=to_datetime,
            to_datetime__gt=from_datetime,
        )
    if active_holds.exists():
        raise ValidationError({"plot": "An overlapping active block or hold already exists for this plot."})
    PlotHold.objects.create(
        plot=plot,
        action_type=PlotHold.ActionType.BLOCK if new_status == Plot.Status.BLOCKED else PlotHold.ActionType.HOLD,
        reason=reason,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        notes=notes or "",
        created_by=user,
    )


def _change_locked_plot_status(plot, new_status, reason, user, from_datetime=None, to_datetime=None, notes=""):
    reason = (reason or "").strip()
    validate_status_transition(plot.status, new_status)
    _validate_reason(new_status, reason)
    if (from_datetime or to_datetime or notes) and new_status not in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        raise ValidationError({"status": "Hold timing and notes are only valid for block or hold operations."})

    old_status = plot.status
    now = timezone.now()
    if old_status in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        _close_active_holds(plot, now)
    if new_status in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        _create_hold_record(plot, new_status, reason, user, from_datetime, to_datetime, notes)

    plot.status = new_status
    plot.save(update_fields=["status", "updated_at"])
    PlotStatusHistory.objects.create(
        plot=plot, old_status=old_status, new_status=new_status, reason=reason, changed_by=user
    )
    return plot


def change_plot_status(*, plot, new_status, reason, user, from_datetime=None, to_datetime=None, notes=""):
    """Atomically lock a plot, transition it, and write immutable audit records."""
    with transaction.atomic():
        locked_plot = Plot.objects.select_for_update().get(pk=plot.pk, organization=plot.organization)
        return _change_locked_plot_status(
            locked_plot, new_status, reason, user, from_datetime, to_datetime, notes
        )


def block_plot(*, plot, reason, user, from_datetime=None, to_datetime=None, notes=""):
    return change_plot_status(
        plot=plot, new_status=Plot.Status.BLOCKED, reason=reason, user=user,
        from_datetime=from_datetime, to_datetime=to_datetime, notes=notes,
    )


def hold_plot(*, plot, reason, user, from_datetime=None, to_datetime=None, notes=""):
    return change_plot_status(
        plot=plot, new_status=Plot.Status.HOLD, reason=reason, user=user,
        from_datetime=from_datetime, to_datetime=to_datetime, notes=notes,
    )


def release_plot(*, plot, reason, user):
    if plot.status not in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        raise ValidationError({"status": "Only blocked or held plots can be released."})
    return change_plot_status(plot=plot, new_status=Plot.Status.AVAILABLE, reason=reason, user=user)


def bulk_change_plot_status(*, plots, new_status, reason, user):
    plot_ids = sorted({plot.pk for plot in plots})
    if not plot_ids:
        raise ValidationError({"plot_ids": "Provide at least one plot ID."})
    organization_id = plots[0].organization_id
    with transaction.atomic():
        locked_plots = list(
            Plot.objects.select_for_update().filter(organization_id=organization_id, pk__in=plot_ids).order_by("pk")
        )
        if len(locked_plots) != len(plot_ids):
            raise ValidationError({"plot_ids": "One or more plots do not exist in this organization."})
        # Validate every requested transition before making any changes.
        for plot in locked_plots:
            validate_status_transition(plot.status, new_status)
            _validate_reason(new_status, (reason or "").strip())
        updated = [
            change_plot_status(plot=plot, new_status=new_status, reason=reason, user=user)
            for plot in locked_plots
        ]
    return updated
