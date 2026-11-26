from datetime import date
from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (Agreement, AgreementSignedDocument, Installment, InstallmentPayment, Payment, PaymentAdjustment,
    PaymentAllocation, PaymentAdvance, PaymentReceipt, PaymentRefund, PaymentStatusHistory, Plot, PlotBooking,
    Possession, Registry, RegistryCharge, RegistryStatusHistory)
from .services import change_plot_status
from system_settings.models import MasterData


def _decimal_total(values):
    """Sum money in Python so Decimal precision is explicit at every boundary."""
    return sum((value or Decimal("0.00") for value in values), Decimal("0.00"))


def _confirmed(booking):
    if booking.status != PlotBooking.Status.CONFIRMED:
        raise ValidationError({"booking": "This operation requires a confirmed booking."})


def _positive(value, field="amount"):
    if value is None or value <= Decimal("0"):
        raise ValidationError({field: "Must be greater than zero."})


def payment_totals(booking):
    settled = [Payment.Status.SUCCESS, Payment.Status.REFUNDED]
    gross = _decimal_total(PaymentAllocation.objects.filter(booking=booking, payment__status__in=settled).values_list("amount", flat=True))
    gross += _decimal_total(PaymentAdvance.objects.filter(booking=booking, payment__status__in=settled).values_list("amount", flat=True))
    gross += _decimal_total(Payment.objects.filter(booking=booking, payment_allocations__isnull=True, payment_advances__isnull=True, status__in=settled).values_list("amount", flat=True))
    refunded = _decimal_total(PaymentRefund.objects.filter(Q(payment__payment_allocations__booking=booking) | Q(payment__payment_advances__booking=booking), status=PaymentRefund.Status.COMPLETED).distinct().values_list("amount", flat=True))
    adjusted = _decimal_total(PaymentAdjustment.objects.filter(Q(payment__payment_allocations__booking=booking) | Q(payment__payment_advances__booking=booking)).distinct().values_list("amount", flat=True))
    net = gross - refunded - adjusted
    return {"final_price": booking.final_price, "total_paid": gross, "total_refunded": refunded,
            "net_paid": net, "outstanding_amount": max((booking.final_price or Decimal("0.00")) - net, Decimal("0.00")) if booking.final_price is not None else None}


def organization_net_settled_revenue(organization):
    """Return settled organization revenue using the same payment ledger rules."""
    settled = [Payment.Status.SUCCESS, Payment.Status.REFUNDED]
    gross = _decimal_total(
        PaymentAllocation.objects.filter(
            payment__organization=organization, payment__status__in=settled,
        ).values_list("amount", flat=True)
    )
    gross += _decimal_total(
        PaymentAdvance.objects.filter(
            payment__organization=organization, payment__status__in=settled,
        ).values_list("amount", flat=True)
    )
    gross += _decimal_total(
        Payment.objects.filter(
            organization=organization,
            payment_allocations__isnull=True,
            payment_advances__isnull=True,
            status__in=settled,
        ).values_list("amount", flat=True)
    )
    refunded = _decimal_total(
        PaymentRefund.objects.filter(
            organization=organization, status=PaymentRefund.Status.COMPLETED,
        ).values_list("amount", flat=True)
    )
    adjusted = _decimal_total(
        PaymentAdjustment.objects.filter(payment__organization=organization).values_list("amount", flat=True)
    )
    return gross - refunded - adjusted


def _payment_transition(payment, new_status):
    allowed = {Payment.Status.PENDING: {Payment.Status.SUCCESS, Payment.Status.FAILED, Payment.Status.CANCELLED},
               Payment.Status.SUCCESS: {Payment.Status.REFUNDED}, Payment.Status.FAILED: set(),
               Payment.Status.CANCELLED: set(), Payment.Status.REFUNDED: set()}
    if new_status not in allowed.get(payment.status, set()):
        raise ValidationError({"status": f"Cannot change payment status from '{payment.status}' to '{new_status}'."})


def create_payment(*, booking, amount, payment_method, transaction_reference, payment_date, notes, user):
    return create_allocated_payment(organization=booking.organization, amount=amount, payment_method=payment_method,
        payment_date=payment_date, transaction_reference=transaction_reference, notes=notes, user=user,
        allocations=[{"booking": booking, "amount": amount}], compatibility_booking=booking)


def record_initial_booking_payment(*, booking, amount, payment_method, transaction_reference, user):
    with transaction.atomic():
        payment = create_allocated_payment(
            organization=booking.organization, amount=amount, payment_method=payment_method,
            payment_date=timezone.localdate(), transaction_reference=transaction_reference,
            notes="", user=user, allocations=[{"booking": booking, "amount": amount}],
            compatibility_booking=booking, initial_booking=True,
        )
        return confirm_payment(payment=payment, user=user, initial_booking=True)


def _refresh_booking_paid_amounts(payment):
    bookings = PlotBooking.objects.filter(
        Q(payment_allocations__payment=payment) | Q(payment_advances__payment=payment) | Q(pk=payment.booking_id)
    ).values_list("pk", flat=True).distinct()
    for booking in PlotBooking.objects.select_for_update().filter(pk__in=bookings).order_by("pk"):
        PlotBooking.objects.filter(pk=booking.pk).update(booking_amount_paid=payment_totals(booking)["net_paid"])


def _require_payment_booking_status(booking, initial_booking):
    if initial_booking and booking.status == PlotBooking.Status.PENDING:
        return
    _confirmed(booking)


def _payment_mode_is_valid(organization, value, *, project=None):
    value = (value or "").strip().lower()
    configured = MasterData.objects.filter(
        organization=organization, project=project, category__code="payment_mode", is_active=True
    )
    allowed = set(configured.values_list("code", flat=True))
    if not allowed and project is None:
        allowed = {choice for choice, _ in Payment.Method.choices} | {"net_banking", "wallet"}
    if value not in allowed:
        raise ValidationError({"payment_mode": "Use an active project payment mode."})
    return value


def _allocation_outstanding(*, booking, installment=None, registry_charge=None):
    settled_statuses = [Payment.Status.SUCCESS, Payment.Status.REFUNDED]
    if installment:
        base = installment.amount
        applied = _decimal_total(PaymentAllocation.objects.filter(installment=installment, payment__status__in=settled_statuses).values_list("amount", flat=True))
        applied += _decimal_total(InstallmentPayment.objects.filter(installment=installment, payment__status__in=settled_statuses).values_list("amount", flat=True))
        refunded = _decimal_total(PaymentRefund.objects.filter(payment__payment_allocations__installment=installment, status=PaymentRefund.Status.COMPLETED).values_list("amount", flat=True))
        adjusted = _decimal_total(PaymentAdjustment.objects.filter(payment__payment_allocations__installment=installment).values_list("amount", flat=True))
    elif registry_charge:
        base = registry_charge.amount
        applied = _decimal_total(PaymentAllocation.objects.filter(registry_charge=registry_charge, payment__status__in=settled_statuses).values_list("amount", flat=True))
        refunded = _decimal_total(PaymentRefund.objects.filter(payment__payment_allocations__registry_charge=registry_charge, status=PaymentRefund.Status.COMPLETED).values_list("amount", flat=True))
        adjusted = _decimal_total(PaymentAdjustment.objects.filter(payment__payment_allocations__registry_charge=registry_charge).values_list("amount", flat=True))
    else:
        if Installment.objects.filter(booking=booking).exists():
            base = booking.final_price if booking.final_price is not None else booking.plot.total_price
            applied = _decimal_total(PaymentAllocation.objects.filter(booking=booking, payment__status__in=settled_statuses).values_list("amount", flat=True))
            applied += _decimal_total(InstallmentPayment.objects.filter(installment__booking=booking, payment__status__in=settled_statuses).values_list("amount", flat=True))
            legacy = _decimal_total(Payment.objects.filter(booking=booking, payment_allocations__isnull=True, status__in=settled_statuses).values_list("amount", flat=True))
            applied += legacy
            refunded = _decimal_total(PaymentRefund.objects.filter(Q(payment__payment_allocations__booking=booking) | Q(payment__payment_advances__booking=booking), status=PaymentRefund.Status.COMPLETED).distinct().values_list("amount", flat=True))
            adjusted = _decimal_total(PaymentAdjustment.objects.filter(Q(payment__payment_allocations__booking=booking) | Q(payment__payment_advances__booking=booking)).distinct().values_list("amount", flat=True))
            outstanding = max(base - applied + refunded + adjusted, Decimal("0"))
            if outstanding > 0:
                raise ValidationError({"booking_allocations": "Allocate this booking payment to one of its installments."})
            return Decimal("0")
        base = booking.final_price if booking.final_price is not None else booking.plot.total_price
        if base is None: raise ValidationError({"booking": "Set a final price or create installments before accepting payment."})
        applied = _decimal_total(PaymentAllocation.objects.filter(booking=booking, installment__isnull=True, registry_charge__isnull=True, payment__status__in=settled_statuses).values_list("amount", flat=True))
        applied += _decimal_total(Payment.objects.filter(booking=booking, payment_allocations__isnull=True, status__in=settled_statuses).values_list("amount", flat=True))
        refunded = _decimal_total(PaymentRefund.objects.filter(payment__payment_allocations__booking=booking, status=PaymentRefund.Status.COMPLETED).values_list("amount", flat=True))
        adjusted = _decimal_total(PaymentAdjustment.objects.filter(payment__payment_allocations__booking=booking).values_list("amount", flat=True))
    return max(base - applied + refunded + adjusted, Decimal("0"))


def create_allocated_payment(*, organization, amount, payment_method, payment_date, transaction_reference, notes, user, allocations, compatibility_booking=None, initial_booking=False):
    _positive(amount)
    if not allocations: raise ValidationError({"booking_allocations": "At least one allocation is required."})
    if payment_date is None: raise ValidationError({"payment_date": "This field is required."})
    # Future-dated entries are permitted; confirmation retains the submitted date for reconciliation.
    with transaction.atomic():
        parsed, advances, total = [], [], Decimal("0")
        for data in allocations:
            booking = PlotBooking.objects.select_for_update().select_related("plot").get(pk=data["booking"].pk)
            if booking.organization_id != organization.id: raise ValidationError({"booking_id": "Use a booking in this organization."})
            _require_payment_booking_status(booking, initial_booking)
            installment, charge = data.get("installment"), data.get("registry_charge")
            value = data["amount"]; _positive(value)
            if installment and (installment.booking_id != booking.id or installment.organization_id != organization.id): raise ValidationError({"installment_id": "Use an installment for the selected booking."})
            if charge and charge.registry.booking_id != booking.id: raise ValidationError({"registry_charge_id": "Use a registry charge for the selected booking."})
            outstanding = _allocation_outstanding(booking=booking, installment=installment, registry_charge=charge)
            applied_value = min(value, outstanding)
            if applied_value > 0:
                parsed.append((booking, installment, charge, applied_value))
                total += applied_value
        # The frontend sends only the due portion in booking_allocations. Any
        # remainder of the received amount is retained as customer advance.
        if total < amount:
            advance_booking = parsed[0][0] if parsed else allocations[0]["booking"]
            advances.append((advance_booking, amount - total))
        payment_booking = compatibility_booking or (parsed[0][0] if parsed else advances[0][0])
        mode = _payment_mode_is_valid(organization, payment_method, project=payment_booking.plot.project)
        payment = Payment.objects.create(organization=organization, booking=payment_booking, payment_id=f"PAY-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}", amount=amount, payment_method=mode, transaction_reference=(transaction_reference or "").strip(), payment_date=payment_date, notes=(notes or "").strip(), received_by=user)
        for booking, installment, charge, value in parsed:
            PaymentAllocation.objects.create(payment=payment, booking=booking, installment=installment, registry_charge=charge, amount=value)
        for booking, value in advances:
            PaymentAdvance.objects.create(payment=payment, booking=booking, amount=value)
        PaymentStatusHistory.objects.create(payment=payment, old_status="", new_status=Payment.Status.PENDING, reason="Payment created", changed_by=user)
        return payment


def confirm_payment(*, payment, user, initial_booking=False):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        _payment_transition(payment, Payment.Status.SUCCESS)
        allocations = list(PaymentAllocation.objects.select_for_update().select_related("booking", "installment", "registry_charge").filter(payment=payment))
        for allocation in allocations:
            locked_booking = PlotBooking.objects.select_for_update().select_related("plot").get(pk=allocation.booking_id)
            _require_payment_booking_status(locked_booking, initial_booking)
            if allocation.amount > _allocation_outstanding(booking=locked_booking, installment=allocation.installment, registry_charge=allocation.registry_charge):
                raise ValidationError({"amount": "Payment allocation is no longer outstanding."})
        payment.status = Payment.Status.SUCCESS; payment.received_by = user
        payment.save(update_fields=["status", "received_by", "updated_at"])
        PaymentReceipt.objects.get_or_create(payment=payment, defaults={"organization": payment.organization, "receipt_number": f"RCT-{payment.organization_id}-{payment.id:08d}"})
        PaymentStatusHistory.objects.create(payment=payment, old_status=Payment.Status.PENDING, new_status=Payment.Status.SUCCESS, reason="Payment confirmed", changed_by=user)
        for allocation in allocations:
            if allocation.installment: refresh_installment_status(allocation.installment)
        _refresh_booking_paid_amounts(payment)
        from .customer_services import advance_customer_lifecycle
        booking_ids = {allocation.booking_id for allocation in allocations}
        if payment.booking_id:
            booking_ids.add(payment.booking_id)
        for booking in PlotBooking.objects.filter(pk__in=booking_ids).select_related("customer"):
            if booking.customer_id:
                advance_customer_lifecycle(
                    booking.customer,
                    booking.customer.Status.ENGAGED,
                    reason="First recorded payment",
                    actor=user,
                )
        return payment


def fail_payment(*, payment):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        _payment_transition(payment, Payment.Status.FAILED)
        payment.status = Payment.Status.FAILED; payment.save(update_fields=["status", "updated_at"])
        return payment


def refund_payment(*, payment, amount, reason, refund_date, user):
    _positive(amount)
    if not (reason or "").strip(): raise ValidationError({"reason": "Provide a refund reason."})
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status not in {Payment.Status.SUCCESS, Payment.Status.REFUNDED}:
            raise ValidationError({"payment": "Only successful payments can be refunded."})
        already = _decimal_total(payment.refunds.exclude(status=PaymentRefund.Status.REJECTED).values_list("amount", flat=True))
        if already + amount > payment.amount: raise ValidationError({"amount": "Refund exceeds the payment amount."})
        refund = PaymentRefund.objects.create(organization=payment.organization, payment=payment, amount=amount, reason=reason.strip(), refund_date=refund_date, requested_by=user)
        return refund


def approve_refund(*, refund, user):
    with transaction.atomic():
        refund = PaymentRefund.objects.select_for_update().select_related("payment").get(pk=refund.pk)
        if refund.status != PaymentRefund.Status.PENDING: raise ValidationError({"refund": "Only pending refunds can be approved."})
        refund.status = PaymentRefund.Status.COMPLETED; refund.approved_by = user; refund.processed_by = user; refund.approved_at = timezone.now(); refund.save(update_fields=["status", "approved_by", "processed_by", "approved_at"])
        if _decimal_total(refund.payment.refunds.filter(status=PaymentRefund.Status.COMPLETED).values_list("amount", flat=True)) == refund.payment.amount:
            old = refund.payment.status; refund.payment.status = Payment.Status.REFUNDED; refund.payment.save(update_fields=["status", "updated_at"]); PaymentStatusHistory.objects.create(payment=refund.payment, old_status=old, new_status=Payment.Status.REFUNDED, reason="Fully refunded", changed_by=user)
        _refresh_booking_paid_amounts(refund.payment)
        return refund


def adjust_payment(*, payment, amount, reason, user):
    _positive(amount)
    if not (reason or "").strip(): raise ValidationError({"reason": "Provide an adjustment reason."})
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status not in {Payment.Status.SUCCESS, Payment.Status.REFUNDED}: raise ValidationError({"payment": "Only effective payments can be adjusted."})
        existing = _decimal_total(payment.adjustments.values_list("amount", flat=True))
        if existing + amount > payment.amount: raise ValidationError({"amount": "Adjustment exceeds the payment amount."})
        adjustment = PaymentAdjustment.objects.create(payment=payment, amount=amount, reason=reason.strip(), created_by=user)
        _refresh_booking_paid_amounts(payment)
        return adjustment


def refresh_installment_status(installment):
    paid = _decimal_total(installment.allocations.values_list("amount", flat=True))
    if installment.status == Installment.Status.CANCELLED: return installment
    new_status = Installment.Status.PAID if paid == installment.amount else Installment.Status.PARTIALLY_PAID if paid else (Installment.Status.OVERDUE if installment.due_date < date.today() else Installment.Status.PENDING)
    if new_status != installment.status:
        installment.status = new_status; installment.save(update_fields=["status", "updated_at"])
    return installment


def create_installment(*, booking, installment_number, title, due_date, amount, notes):
    _confirmed(booking); _positive(amount)
    installment = Installment(organization=booking.organization, booking=booking, installment_number=installment_number,
                              title=title, due_date=due_date, amount=amount, notes=notes or "")
    installment.full_clean(); installment.save(); return installment


def allocate_payment(*, payment, installment, amount):
    _positive(amount)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        installment = Installment.objects.select_for_update().get(pk=installment.pk)
        if payment.booking_id != installment.booking_id: raise ValidationError({"installment": "Payment and installment must belong to the same booking."})
        if payment.status != Payment.Status.SUCCESS: raise ValidationError({"payment": "Only successful payments can be allocated."})
        allocated = _decimal_total(payment.allocations.values_list("amount", flat=True))
        paid = _decimal_total(installment.allocations.values_list("amount", flat=True))
        if allocated + amount > payment.amount: raise ValidationError({"amount": "Allocation exceeds payment amount."})
        if paid + amount > installment.amount: raise ValidationError({"amount": "Allocation exceeds installment amount."})
        allocation = InstallmentPayment.objects.create(payment=payment, installment=installment, amount=amount)
        refresh_installment_status(installment); return allocation


def _transition(instance, new_status, transitions, label):
    if new_status not in transitions.get(instance.status, set()): raise ValidationError({"status": f"Cannot change {label} status from '{instance.status}' to '{new_status}'."})
    instance.status = new_status; instance.save(update_fields=["status", "updated_at"]); return instance


AGREEMENT_TRANSITIONS = {Agreement.Status.DRAFT: {Agreement.Status.READY, Agreement.Status.CANCELLED}, Agreement.Status.READY: {Agreement.Status.SIGNED, Agreement.Status.CANCELLED}, Agreement.Status.SIGNED: set(), Agreement.Status.CANCELLED: set()}
REGISTRY_TRANSITIONS = {Registry.Status.PENDING: {Registry.Status.SCHEDULED, Registry.Status.IN_PROCESS, Registry.Status.CANCELLED}, Registry.Status.SCHEDULED: {Registry.Status.COMPLETED, Registry.Status.CANCELLED}, Registry.Status.IN_PROCESS: {Registry.Status.COMPLETED, Registry.Status.CANCELLED}, Registry.Status.COMPLETED: set(), Registry.Status.CANCELLED: set()}
POSSESSION_TRANSITIONS = {Possession.Status.PENDING: {Possession.Status.SCHEDULED, Possession.Status.CANCELLED}, Possession.Status.SCHEDULED: {Possession.Status.COMPLETED, Possession.Status.CANCELLED}, Possession.Status.COMPLETED: set(), Possession.Status.CANCELLED: set()}


def create_agreement(*, booking, **data):
    _confirmed(booking)
    if Agreement.objects.filter(booking=booking).exists(): raise ValidationError({"booking": "An agreement already exists for this booking."})
    return Agreement.objects.create(organization=booking.organization, booking=booking, **data)
def transition_agreement(*, agreement, status):
    with transaction.atomic():
        locked_agreement = Agreement.objects.select_for_update().get(pk=agreement.pk)
        if status == Agreement.Status.SIGNED and not AgreementSignedDocument.objects.filter(agreement=locked_agreement, superseded_at__isnull=True).exists():
            raise ValidationError({"signed_copy": "Upload the final agreement copy signed by both parties before signing the Agreement."})
        return _transition(locked_agreement, status, AGREEMENT_TRANSITIONS, "agreement")
def calculate_registry_charges(*, organization, booking, consideration_amount):
    result = []
    for item in MasterData.objects.filter(
        organization=organization, project=booking.plot.project,
        category__code="registry_charge_type", is_active=True,
    ):
        config = item.description.strip()
        try: kind, value = config.split(":", 1); value = Decimal(value)
        except (ValueError, ArithmeticError): kind, value = "fixed", Decimal("0")
        amount = value if kind == "fixed" else (consideration_amount * value / Decimal("100"))
        result.append((item.code, item.name, kind, value, amount.quantize(Decimal("0.01"))))
    return result


def create_registry(*, booking, **data):
    with transaction.atomic():
        booking = PlotBooking.objects.select_for_update().select_related("plot").get(pk=booking.pk)
        _confirmed(booking)
        if booking.plot.status != Plot.Status.BOOKED: raise ValidationError({"plot": "Registry requires a booked plot."})
        if not Agreement.objects.filter(booking=booking, status=Agreement.Status.SIGNED).exists(): raise ValidationError({"agreement": "A signed agreement is required."})
        from documents.services import validate_customer_documents_for_booking
        validation = validate_customer_documents_for_booking(booking.customer)
        if not validation["allowed"]:
            raise ValidationError({"documents": validation})
        if Registry.objects.filter(booking=booking).exists(): raise ValidationError({"booking": "A registry already exists for this booking."})
        registry = Registry.objects.create(organization=booking.organization, booking=booking, **data)
        consideration = registry.consideration_amount or booking.final_price or booking.plot.total_price or Decimal("0")
        for code, label, kind, value, amount in calculate_registry_charges(organization=booking.organization, booking=booking, consideration_amount=consideration): RegistryCharge.objects.create(registry=registry, code=code, label=label, calculation_type=kind, calculation_value=value, amount=amount)
        RegistryStatusHistory.objects.create(registry=registry, old_status="", new_status=Registry.Status.PENDING, remarks="Registry created", changed_by=data.get("created_by"))
        return registry
def transition_registry(*, registry, status, user=None, remarks=""):
    with transaction.atomic():
        registry = Registry.objects.select_for_update().select_related("booking__lead", "booking__plot").get(pk=registry.pk)
        if status == Registry.Status.COMPLETED:
            if not registry.registry_date: raise ValidationError({"registry_date": "Registry date is required before completion."})
            if payment_totals(registry.booking)["outstanding_amount"] > Decimal("0.00"):
                raise ValidationError({"payments": "All booking dues must be paid before registry completion."})
            from documents.services import validate_customer_documents_for_booking
            validation = validate_customer_documents_for_booking(registry.booking.customer)
            if not validation["allowed"]: raise ValidationError({"documents": validation})
        old = registry.status; result = _transition(registry, status, REGISTRY_TRANSITIONS, "registry")
        RegistryStatusHistory.objects.create(registry=result, old_status=old, new_status=status, remarks=remarks, changed_by=user)
        if status == Registry.Status.COMPLETED:
            change_plot_status(
                plot=registry.booking.plot,
                new_status=Plot.Status.SOLD,
                reason="Registry completed",
                user=user,
            )
        return result
def create_possession(*, booking, **data):
    _confirmed(booking)
    if not Registry.objects.filter(booking=booking, status=Registry.Status.COMPLETED).exists(): raise ValidationError({"registry": "A completed registry is required."})
    if Possession.objects.filter(booking=booking).exists(): raise ValidationError({"booking": "A possession record already exists for this booking."})
    return Possession.objects.create(organization=booking.organization, booking=booking, **data)
def transition_possession(*, possession, status):
    with transaction.atomic(): return _transition(Possession.objects.select_for_update().get(pk=possession.pk), status, POSSESSION_TRANSITIONS, "possession")
