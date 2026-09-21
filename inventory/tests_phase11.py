from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Block, Installment, Payment, PaymentAllocation, Plot, PlotBooking
from .phase5_services import create_allocated_payment, refresh_overdue_installments


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
class Phase11PaymentTests(TestCase):
    """FR-P11-01..08 and NFR-P11-01/02 backend coverage."""

    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="payment-manager", password="password123")
        self.telecaller = user_model.objects.create_user(username="payment-telecaller", password="password123")
        self.organization = Organization.objects.create(name="Payment Org", slug="payment-org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER)
        self.block = Block.objects.create(organization=self.organization, name="A", code="A")
        self.lead = Lead.objects.create(organization=self.organization, first_name="Pay", last_name="Customer", phone="9999999999")
        self.plot = Plot.objects.create(organization=self.organization, block=self.block, plot_number="A-1", size=Decimal("100"), total_price=Decimal("100000"), status=Plot.Status.BOOKED)
        self.booking = PlotBooking.objects.create(organization=self.organization, lead=self.lead, plot=self.plot, status=PlotBooking.Status.CONFIRMED, final_price=Decimal("100000"))
        self.client = APIClient(); self.client.force_authenticate(self.manager)

    def test_payment_idempotency_replays_same_payment_and_rejects_conflict(self):
        url = reverse("inventory:managed-payments", args=[self.organization.slug])
        payload = {"amount": "1000", "payment_mode": "cash", "payment_date": "2026-09-20", "booking_allocations": [{"booking_id": self.booking.id, "amount": "1000"}]}
        first = self.client.post(url, payload, format="json", HTTP_X_IDEMPOTENCY_KEY="payment-key-1")
        second = self.client.post(url, payload, format="json", HTTP_X_IDEMPOTENCY_KEY="payment-key-1")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Payment.objects.count(), 1)
        conflict = self.client.post(url, {**payload, "amount": "2000", "booking_allocations": [{"booking_id": self.booking.id, "amount": "2000"}]}, format="json", HTTP_X_IDEMPOTENCY_KEY="payment-key-1")
        self.assertEqual(conflict.status_code, 409)

    def test_payment_and_allocation_rows_are_immutable(self):
        payment = create_allocated_payment(organization=self.organization, amount=Decimal("1000"), payment_method="cash", payment_date=date.today(), transaction_reference="x", notes="", user=self.manager, allocations=[{"booking": self.booking, "amount": Decimal("1000")}], idempotency_key="immutable-1")
        payment.notes = "tampered"
        with self.assertRaises(ValidationError):
            payment.save()
        with self.assertRaises(ValidationError):
            payment.delete()
        allocation = payment.payment_allocations.get()
        allocation.amount = Decimal("999")
        with self.assertRaises(ValidationError):
            allocation.save()
        with self.assertRaises(ValidationError):
            allocation.delete()

    def test_overdue_refresh_marks_past_due_installment_and_advance_balance_is_preserved(self):
        installment = Installment.objects.create(organization=self.organization, booking=self.booking, installment_number=1, title="Booking", due_date=date.today() - timedelta(days=1), amount=Decimal("1000"))
        refresh_overdue_installments()
        installment.refresh_from_db()
        self.assertEqual(installment.status, Installment.Status.OVERDUE)
        payment = create_allocated_payment(organization=self.organization, amount=Decimal("1500"), payment_method="cash", payment_date=date.today(), transaction_reference="advance", notes="", user=self.manager, allocations=[{"booking": self.booking, "installment": installment, "amount": Decimal("1500")}], idempotency_key="advance-1")
        self.assertEqual(payment.advance_amount, Decimal("500.00"))

    def test_telecaller_cannot_approve_refund(self):
        payment = Payment.objects.create(organization=self.organization, booking=self.booking, payment_id="PAY-SEC-1", amount=Decimal("1000"), payment_method="cash", status=Payment.Status.SUCCESS, payment_date=date.today(), received_by=self.manager)
        refund_url = reverse("inventory:managed-payment-refund", args=[self.organization.slug, payment.id])
        self.client.force_authenticate(self.manager)
        requested = self.client.post(refund_url, {"amount": "100", "reason": "test", "refund_date": "2026-09-20"}, format="json")
        self.assertEqual(requested.status_code, 201, requested.data)
        refund_id = requested.data["id"]
        self.client.force_authenticate(self.telecaller)
        approve = reverse("inventory:managed-payment-refund-approve", args=[self.organization.slug, payment.id, refund_id])
        self.assertEqual(self.client.post(approve, {}, format="json").status_code, 403)
