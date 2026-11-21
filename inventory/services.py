import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import OperationalError, transaction
from django.utils import timezone
from datetime import timedelta

from core.exceptions import is_database_busy_error

from .models import (
    BookingIdempotencyKey,
    BookingReceiptSequence,
    Customer,
    CustomerCodeSequence,
    Plot,
    PlotBooking,
    PlotHold,
    PlotStatusHistory,
)


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
    PlotBooking.Status.CREATED: {PlotBooking.Status.PENDING, PlotBooking.Status.CANCELLED, PlotBooking.Status.EXPIRED},
    PlotBooking.Status.PENDING: {PlotBooking.Status.PARTIALLY_PAID, PlotBooking.Status.CONFIRMED, PlotBooking.Status.CANCELLED, PlotBooking.Status.EXPIRED},
    PlotBooking.Status.PARTIALLY_PAID: {PlotBooking.Status.CONFIRMED, PlotBooking.Status.CANCELLED, PlotBooking.Status.EXPIRED},
    PlotBooking.Status.CONFIRMED: {PlotBooking.Status.CANCELLED},
    PlotBooking.Status.CANCELLED: set(),
    PlotBooking.Status.EXPIRED: set(),
}


class BookingDocumentValidationError(ValidationError):
    """Carries structured document failures without violating ValidationError's flat dict contract."""
    def __init__(self, document_validation):
        super().__init__({"detail": "Customer documents are incomplete."})
        self.document_validation = document_validation


class PlotAvailabilityConflict(ValidationError):
    code = "plot_conflict"


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
        if locked_plot.status == Plot.Status.HOLD:
            owner_hold = locked_plot.hold_records.filter(
                action_type=PlotHold.ActionType.HOLD,
                released_at__isnull=True,
            ).order_by("-created_at", "-id").first()
            if not owner_hold or owner_hold.created_by_id != user.id:
                raise ValidationError({"plot_id": "Only an available plot or your own active hold can be selected for booking."})
        elif locked_plot.status != Plot.Status.AVAILABLE:
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
        # An available plot becomes held for the pending booking. An existing hold
        # owned by this user is already in the required state and is preserved.
        if locked_plot.status == Plot.Status.AVAILABLE:
            change_plot_status(
                plot=locked_plot, new_status=Plot.Status.HOLD,
                reason="Plot selected for booking", user=user, notes=booking.notes,
            )
        return booking


def _next_project_number(sequence_model, project):
    locked_project = project.__class__.objects.select_for_update().get(pk=project.pk)
    sequence, _ = sequence_model.objects.get_or_create(project=locked_project, defaults={"next_number": 1})
    sequence = sequence_model.objects.select_for_update().get(pk=sequence.pk)
    number = sequence.next_number
    sequence.next_number += 1
    sequence.save(update_fields=["next_number"])
    return number


def _customer_for_booking(*, organization, project, lead):
    customer = Customer.objects.filter(organization=organization, project=project, lead=lead).first()
    if customer:
        return customer
    number = _next_project_number(CustomerCodeSequence, project)
    return Customer.objects.create(
        organization=organization,
        project=project,
        lead=lead,
        customer_code=f"{project.code}-C-{number:06d}",
        full_name=lead.full_name,
        phone=lead.phone or "",
        email=lead.email or "",
        address=lead.address or "",
    )


def _booking_receipt_number(project):
    number = _next_project_number(BookingReceiptSequence, project)
    return f"{project.code}-BR-{number:06d}"


def create_idempotent_booking(*, organization, project, lead, plot, user, idempotency_key, body=None, site_visit=None, notes="", initial_payment="0", payment_mode=None, transaction_reference=""):
    """Create the Phase 9 booking in one serialized transaction."""
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError({"idempotency_key": "X-Idempotency-Key is required."})
    payload = body or {"lead_id": lead.pk, "plot_id": plot.pk, "initial_payment": str(initial_payment), "notes": notes}
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    with transaction.atomic():
        existing = BookingIdempotencyKey.objects.select_for_update().filter(
            organization=organization, project=project, key=key
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                error = ValidationError({"idempotency_key": "The same key was already used with a different request."})
                error.code = "idempotency_conflict"
                raise error
            return existing.booking

        try:
            amount = Decimal(str(initial_payment or "0"))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"initial_payment": "Use a valid decimal amount."}) from error
        if not amount.is_finite() or amount < 0:
            raise ValidationError({"initial_payment": "Initial payment cannot be negative."})

        locked_plot = Plot.objects.select_for_update().get(pk=plot.pk, organization=organization, project=project)
        locked_lead = lead.__class__.objects.select_for_update().get(pk=lead.pk, organization=organization)
        if locked_lead.lifecycle_status not in PlotBooking.allowed_lead_statuses():
            raise ValidationError({"lead_id": "A completed site visit is required before creating a booking."})
        if locked_plot.status == Plot.Status.HOLD:
            active_hold = locked_plot.hold_records.filter(released_at__isnull=True).order_by("-created_at", "-id").first()
            if not active_hold or active_hold.created_by_id != user.id:
                raise PlotAvailabilityConflict({"plot_id": "Only an available plot or your own active hold can be booked."})
        elif locked_plot.status != Plot.Status.AVAILABLE:
            raise PlotAvailabilityConflict({"plot_id": "Only an available plot can be booked."})
        if PlotBooking.objects.filter(
            organization=organization, plot=locked_plot,
            status__in=[PlotBooking.Status.CREATED, PlotBooking.Status.PENDING, PlotBooking.Status.PARTIALLY_PAID, PlotBooking.Status.CONFIRMED],
        ).exists():
            raise PlotAvailabilityConflict({"plot_id": "This plot already has an active booking."})

        customer = _customer_for_booking(organization=organization, project=project, lead=locked_lead)
        total = locked_plot.total_price or Decimal("0")
        from system_settings.parameters import PARAMETER_REGISTRY
        from system_settings.services import UnknownSystemParameter, get_system_parameter
        try:
            booking_hold_days = int(get_system_parameter(organization, "booking_hold_days", project=project))
        except UnknownSystemParameter:
            booking_hold_days = int(PARAMETER_REGISTRY["booking_hold_days"].default)
        try:
            grace_minutes = int(get_system_parameter(organization, "payment_pending_grace_minutes", project=project))
        except UnknownSystemParameter:
            grace_minutes = int(PARAMETER_REGISTRY["payment_pending_grace_minutes"].default)
        try:
            minimum_percent = Decimal(str(get_system_parameter(organization, "booking_minimum_payment_percent", project=project)))
        except UnknownSystemParameter:
            minimum_percent = Decimal(str(PARAMETER_REGISTRY["booking_minimum_payment_percent"].default))
        minimum_amount = (total * minimum_percent / Decimal("100")).quantize(Decimal("0.01"))
        now = timezone.now()
        booking = PlotBooking.objects.create(
            organization=organization,
            project=project,
            customer=customer,
            lead=locked_lead,
            plot=locked_plot,
            site_visit=site_visit,
            booking_code=f"{project.code}-BK-{timezone.now().strftime('%Y%m%d%H%M%S')}-{locked_plot.pk}",
            status=PlotBooking.Status.PENDING,
            notes=(notes or "").strip(),
            final_price=total,
            total_amount=total,
            net_amount=total,
            booking_receipt_number=_booking_receipt_number(project),
            created_by=user,
        )
        booking.full_clean()
        change_plot_status(plot=locked_plot, new_status=Plot.Status.BOOKED, reason="Booking created", user=user)
        from .customer_services import advance_customer_lifecycle
        advance_customer_lifecycle(customer, Customer.Status.ACTIVE, reason="Booking created", actor=user)
        from .phase5_services import payment_totals, record_initial_booking_payment
        if amount:
            record_initial_booking_payment(
                booking=booking, amount=amount, payment_method=payment_mode,
                transaction_reference=transaction_reference, user=user,
            )
        paid = payment_totals(booking)["net_paid"]
        booking.booking_amount_paid = paid
        if paid > 0:
            booking.status = PlotBooking.Status.PARTIALLY_PAID
        if paid <= 0:
            booking.hold_expires_at = now + timedelta(minutes=grace_minutes)
        elif paid < minimum_amount:
            booking.hold_expires_at = now + timedelta(days=booking_hold_days)
        booking.save(update_fields=["status", "hold_expires_at", "updated_at"])
        BookingIdempotencyKey.objects.create(
            organization=organization, project=project, key=key, request_hash=request_hash, booking=booking
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
        if locked_plot.status == Plot.Status.HOLD:
            change_plot_status(plot=locked_plot, new_status=Plot.Status.BOOKED, reason="Booking confirmed", user=user)
        elif locked_plot.status != Plot.Status.BOOKED:
            raise ValidationError({"plot": "Only a held or booked plot can have its booking confirmed."})
        locked_booking.status = PlotBooking.Status.CONFIRMED
        locked_booking.save(update_fields=["status", "updated_at"])
        if locked_booking.customer_id:
            from .customer_services import advance_customer_lifecycle
            advance_customer_lifecycle(locked_booking.customer, Customer.Status.CONVERTED, reason="Booking confirmed", actor=user)
        if locked_booking.lead.lifecycle_status == "site_visit_completed":
            from leads.views import _record_lead_status_transition
            _record_lead_status_transition(
                lead=locked_booking.lead,
                status_value="converted",
                user=user,
                reason="Booking confirmed",
                system=True,
            )
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
        if previous_status in {PlotBooking.Status.CREATED, PlotBooking.Status.PENDING, PlotBooking.Status.PARTIALLY_PAID}:
            if locked_plot.status not in {Plot.Status.HOLD, Plot.Status.BOOKED}:
                raise ValidationError({"plot": "Active booking cancellation requires the plot to be held or booked."})
            if locked_plot.status == Plot.Status.BOOKED:
                change_plot_status(plot=locked_plot, new_status=Plot.Status.CANCELLED, reason=reason, user=user)
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


def _close_active_holds(plot, now, request=None):
    active = list(plot.hold_records.filter(released_at__isnull=True))
    plot.hold_records.filter(pk__in=[item.pk for item in active]).update(released_at=now)
    if active:
        from system_settings.audit import log_bulk_audit
        log_bulk_audit(request=request, module="inventory", action="bulk_update", instances=active, organization=plot.organization,
                       project=plot.project, changed_values={"released_at": now.isoformat()})


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
    expires_at = to_datetime
    if expires_at is None:
        from system_settings.parameters import PARAMETER_REGISTRY
        from system_settings.services import UnknownSystemParameter, get_system_parameter
        try:
            hold_hours = int(get_system_parameter(plot.organization, "plot_hold_hours", project=plot.project))
        except UnknownSystemParameter:
            hold_hours = int(PARAMETER_REGISTRY["plot_hold_hours"].default)
        expires_at = timezone.now() + timedelta(hours=hold_hours)
    PlotHold.objects.create(
        plot=plot,
        action_type=PlotHold.ActionType.BLOCK if new_status == Plot.Status.BLOCKED else PlotHold.ActionType.HOLD,
        reason=reason,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        expires_at=expires_at,
        notes=notes or "",
        created_by=user,
    )


def _change_locked_plot_status(plot, new_status, reason, user, from_datetime=None, to_datetime=None, notes="", request=None):
    reason = (reason or "").strip()
    if new_status in {Plot.Status.HOLD, Plot.Status.BLOCKED} and plot.status == Plot.Status.BOOKED:
        raise PlotAvailabilityConflict({"status": "The plot has already been booked."})
    validate_status_transition(plot.status, new_status)
    _validate_reason(new_status, reason)
    if (from_datetime or to_datetime or notes) and new_status not in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        raise ValidationError({"status": "Hold timing and notes are only valid for block or hold operations."})

    old_status = plot.status
    now = timezone.now()
    if old_status in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        _close_active_holds(plot, now, request=request)
    if new_status in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        _create_hold_record(plot, new_status, reason, user, from_datetime, to_datetime, notes)

    plot.status = new_status
    plot.save(update_fields=["status", "updated_at"])
    PlotStatusHistory.objects.create(
        plot=plot, old_status=old_status, new_status=new_status, reason=reason, changed_by=user
    )
    return plot


def change_plot_status(*, plot, new_status, reason, user, from_datetime=None, to_datetime=None, notes="", request=None):
    """Atomically lock a plot, transition it, and write immutable audit records."""
    try:
        with transaction.atomic():
            locked_plot = Plot.objects.select_for_update().get(pk=plot.pk, organization=plot.organization)
            return _change_locked_plot_status(
                locked_plot, new_status, reason, user, from_datetime, to_datetime, notes, request
            )
    except OperationalError as error:
        if is_database_busy_error(error):
            error.code = "database_busy"
            error.status_code = 503
        raise


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


def release_plot(*, plot, reason, user, request=None):
    if plot.status not in {Plot.Status.BLOCKED, Plot.Status.HOLD}:
        raise ValidationError({"status": "Only blocked or held plots can be released."})
    return change_plot_status(plot=plot, new_status=Plot.Status.AVAILABLE, reason=reason, user=user, request=request)


def bulk_change_plot_status(*, plots, new_status, reason, user):
    plot_ids = sorted({plot.pk for plot in plots})
    if not plot_ids:
        raise ValidationError({"plot_ids": "Provide at least one plot ID."})
    if len(plot_ids) > 500:
        raise ValidationError({"plot_ids": "A bulk plot-status update may contain at most 500 plots."})
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
