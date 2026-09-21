import hashlib
import json
import time
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from threading import Lock

from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.utils import timezone

from system_settings.master_data import validate_plot_status
from system_settings.services import get_system_parameter

from .models import Payment, Plot, PlotBooking, PlotHold, PlotStatusHistory


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
    PlotBooking.Status.PENDING: {PlotBooking.Status.CONFIRMED, PlotBooking.Status.CANCELLED, PlotBooking.Status.EXPIRED},
    PlotBooking.Status.CONFIRMED: {PlotBooking.Status.CANCELLED},
    PlotBooking.Status.CANCELLED: set(),
}

# Database row locks remain the source of truth across processes. This small
# per-plot mutex prevents SQLite development/test connections from all
# entering the same write transaction before SQLite can honor row locking.
_PLOT_OPERATION_LOCKS = defaultdict(Lock)


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


def _booking_request_hash(*, lead, plot, site_visit, notes, initial_payment_amount):
    payload = {
        "lead_id": lead.pk, "plot_id": plot.pk, "site_visit_id": site_visit.pk if site_visit else None,
        "notes": (notes or "").strip(),
        "initial_payment_amount": str(initial_payment_amount or "0"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def create_plot_booking(*, organization, lead, plot, site_visit, notes, user,
                        idempotency_key="", initial_payment_amount=None):
    """FR-P9-03/NFR-P9-03: create the booking, hold, and initial payment atomically."""
    idempotency_key = (idempotency_key or "").strip()
    try:
        initial_payment_amount = Decimal(str(initial_payment_amount or "0"))
    except (InvalidOperation, TypeError) as error:
        raise ValidationError({"initial_payment_amount": "Use a valid amount."}) from error
    if initial_payment_amount < 0:
        raise ValidationError({"initial_payment_amount": "Amount cannot be negative."})
    request_hash = _booking_request_hash(
        lead=lead, plot=plot, site_visit=site_visit, notes=notes,
        initial_payment_amount=initial_payment_amount,
    )
    with transaction.atomic():
        # Serialize idempotent requests for one organization before checking
        # and creating the booking row; this closes the concurrent-replay gap.
        organization.__class__.objects.select_for_update().get(pk=organization.pk)
        if idempotency_key:
            existing = PlotBooking.objects.filter(
                organization=organization, idempotency_key=idempotency_key,
            ).first()
            if existing:
                if existing.idempotency_request_hash != request_hash:
                    raise ValidationError({"idempotency_key": "This key was already used for another booking request."})
                return existing
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
        minimum_payment = get_system_parameter(
            organization, "booking_minimum_payment_amount", Decimal("0"), project=locked_plot.project,
        )
        try:
            minimum_payment = Decimal(str(minimum_payment or "0"))
        except (InvalidOperation, TypeError) as error:
            raise ValidationError({"minimum_payment_amount": "Configured minimum payment is invalid."}) from error
        if initial_payment_amount < minimum_payment:
            raise ValidationError({"initial_payment_amount": f"Minimum booking payment is {minimum_payment}."})
        hold_days = get_system_parameter(
            organization, "booking_hold_window_days", 7, project=locked_plot.project,
        )
        try:
            hold_days = int(hold_days)
        except (TypeError, ValueError) as error:
            raise ValidationError({"booking_hold_window_days": "Configured hold window is invalid."}) from error
        if hold_days <= 0:
            raise ValidationError({"booking_hold_window_days": "Configured hold window must be positive."})
        booking = PlotBooking(
            organization=organization, lead=lead, plot=locked_plot, site_visit=site_visit,
            notes=(notes or "").strip(), created_by=user, final_price=locked_plot.total_price,
            idempotency_key=idempotency_key, idempotency_request_hash=request_hash,
            hold_expires_at=timezone.now() + timedelta(days=hold_days),
            minimum_payment_amount=minimum_payment,
        )
        booking.full_clean()
        booking.save()
        # This re-locks within the enclosing transaction and remains the only status authority.
        change_plot_status(
            plot=locked_plot, new_status=Plot.Status.HOLD,
            reason="Plot selected for booking", user=user, notes=booking.notes,
        )
        if initial_payment_amount > 0:
            Payment.objects.create(
                organization=organization, project=booking.project, booking=booking,
                payment_id=f"BKG-{booking.pk}", amount=initial_payment_amount,
                payment_method=Payment.Method.CASH, status=Payment.Status.SUCCESS,
                payment_date=timezone.localdate(), received_by=user,
                notes="Initial booking payment",
            )
        return booking


def confirm_plot_booking(*, booking, user):
    with transaction.atomic():
        locked_booking = PlotBooking.objects.select_for_update().select_related("organization", "lead").get(pk=booking.pk)
        locked_plot = Plot.objects.select_for_update().get(
            pk=locked_booking.plot_id, organization=locked_booking.organization
        )
        validate_booking_transition(locked_booking.status, PlotBooking.Status.CONFIRMED)
        if not locked_booking.lead.is_qualified:
            raise ValidationError({"lead": "Only a qualified customer can confirm a booking."})
        if locked_booking.lead.ekyc_status != locked_booking.lead.EkycStatus.VERIFIED:
            raise ValidationError({"ekyc_status": "Customer eKYC must be verified before confirmation."})
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


def expire_pending_bookings(*, now=None):
    """FR-P9-06: expire unpaid/pending booking holds and return plots to Available."""
    now = now or timezone.now()
    expired_count = 0
    with transaction.atomic():
        due = list(PlotBooking.objects.select_for_update().filter(
            status=PlotBooking.Status.PENDING, hold_expires_at__isnull=False,
            hold_expires_at__lte=now,
        ).select_related("organization"))
        for booking in due:
            plot = Plot.objects.select_for_update().get(pk=booking.plot_id, organization=booking.organization)
            if plot.status == Plot.Status.HOLD:
                change_plot_status(plot=plot, new_status=Plot.Status.AVAILABLE,
                                   reason="Booking hold expired", user=None)
            booking.status = PlotBooking.Status.EXPIRED
            booking.save(update_fields=["status", "updated_at"])
            expired_count += 1
    return expired_count


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
    validate_plot_status(plot.organization, new_status)
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
    with _PLOT_OPERATION_LOCKS[(plot.organization_id, plot.pk)]:
        for attempt in range(3):
            try:
                with transaction.atomic():
                    locked_plot = Plot.objects.select_for_update().get(pk=plot.pk, organization=plot.organization)
                    return _change_locked_plot_status(
                        locked_plot, new_status, reason, user, from_datetime, to_datetime, notes
                    )
            except OperationalError:
                if attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))


def expire_plot_holds(*, now=None):
    """FR-P8-04: release due holds and write an auditable availability event."""
    now = now or timezone.now()
    expired_count = 0
    with transaction.atomic():
        due_holds = list(
            PlotHold.objects.select_for_update().filter(
                released_at__isnull=True,
                to_datetime__isnull=False,
                to_datetime__lte=now,
            ).select_related("plot", "plot__organization")
        )
        for hold in due_holds:
            plot = Plot.objects.select_for_update().get(pk=hold.plot_id)
            hold.released_at = now
            hold.save(update_fields=["released_at"])
            if plot.status == (Plot.Status.BLOCKED if hold.action_type == PlotHold.ActionType.BLOCK else Plot.Status.HOLD):
                old_status = plot.status
                plot.status = Plot.Status.AVAILABLE
                plot.save(update_fields=["status", "updated_at"])
                PlotStatusHistory.objects.create(
                    plot=plot,
                    old_status=old_status,
                    new_status=Plot.Status.AVAILABLE,
                    reason="Hold expired",
                    changed_by=None,
                )
            expired_count += 1
    return expired_count


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
        validate_plot_status(locked_plots[0].organization, new_status)
        for plot in locked_plots:
            validate_status_transition(plot.status, new_status)
            _validate_reason(new_status, (reason or "").strip())
        updated = [
            change_plot_status(plot=plot, new_status=new_status, reason=reason, user=user)
            for plot in locked_plots
        ]
    return updated
