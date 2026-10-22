from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Agreement, AgreementSignedDocument, Block, Installment, Payment, PaymentAdvance, PaymentRefund, Plot, PlotBooking, Possession, Registry
from .phase5_services import (allocate_payment, confirm_payment, create_agreement, create_installment,
    approve_refund, create_payment, create_possession, create_registry, fail_payment, payment_totals, refund_payment,
    transition_agreement, transition_possession, transition_registry)
from .views import payment_to_dict


class Phase5ServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model(); self.user = user_model.objects.create_user(username="manager", password="x")
        self.org = Organization.objects.create(name="Acme", slug="acme")
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role=OrganizationMembership.Role.MANAGER)
        block = Block.objects.create(organization=self.org, name="A", code="A")
        plot = Plot.objects.create(organization=self.org, block=block, plot_number="1", size=Decimal("100"), total_price=Decimal("1000"), status=Plot.Status.BOOKED)
        lead = Lead.objects.create(organization=self.org, first_name="Ada", phone="1")
        self.booking = PlotBooking.objects.create(organization=self.org, lead=lead, plot=plot, status=PlotBooking.Status.CONFIRMED, final_price=Decimal("1000"), created_by=self.user)

    def test_payment_refund_and_summary(self):
        payment = create_payment(booking=self.booking, amount=Decimal("500"), payment_method=Payment.Method.CASH, transaction_reference="", payment_date=date.today(), notes="", user=self.user)
        confirm_payment(payment=payment, user=self.user)
        refund = refund_payment(payment=payment, amount=Decimal("100"), reason="Correction", refund_date=date.today(), user=self.user)
        approve_refund(refund=refund, user=self.user)
        totals = payment_totals(self.booking)
        self.assertEqual((totals["total_paid"], totals["total_refunded"], totals["net_paid"], totals["outstanding_amount"]), (Decimal("500"), Decimal("100"), Decimal("400"), Decimal("600")))
        with self.assertRaises(ValidationError): refund_payment(payment=payment, amount=Decimal("401"), reason="Too much", refund_date=date.today(), user=self.user)
        with self.assertRaises(ValidationError): confirm_payment(payment=payment, user=self.user)

    def test_fully_refunded_payment_does_not_reduce_current_outstanding_balance(self):
        payment = create_payment(booking=self.booking, amount=Decimal("500"), payment_method=Payment.Method.CASH,
                                 transaction_reference="refund-balance", payment_date=date.today(), notes="", user=self.user)
        confirm_payment(payment=payment, user=self.user)
        refund = refund_payment(payment=payment, amount=Decimal("500"), reason="Full reversal",
                                refund_date=date.today(), user=self.user)
        approve_refund(refund=refund, user=self.user)

        replacement = create_payment(booking=self.booking, amount=Decimal("1000"), payment_method=Payment.Method.CASH,
                                     transaction_reference="replacement-payment", payment_date=date.today(), notes="", user=self.user)
        confirm_payment(payment=replacement, user=self.user)
        self.assertEqual(payment_totals(self.booking)["outstanding_amount"], Decimal("0"))

    def test_allocation_allows_amount_after_completed_refund_reduces_outstanding(self):
        payment = create_payment(booking=self.booking, amount=Decimal("500"), payment_method=Payment.Method.CASH,
                                 transaction_reference="partial-refund", payment_date=date.today(), notes="", user=self.user)
        confirm_payment(payment=payment, user=self.user)
        refund = refund_payment(payment=payment, amount=Decimal("100"), reason="Correction",
                                refund_date=date.today(), user=self.user)
        approve_refund(refund=refund, user=self.user)

        replacement = create_payment(booking=self.booking, amount=Decimal("600"), payment_method=Payment.Method.CASH,
                                     transaction_reference="remaining-balance", payment_date=date.today(), notes="", user=self.user)

        self.assertEqual(replacement.amount, Decimal("600"))

    def test_excess_payment_is_accepted_and_recorded_as_advance(self):
        payment = create_payment(booking=self.booking, amount=Decimal("1200"), payment_method=Payment.Method.CASH,
                                 transaction_reference="advance-payment", payment_date=date.today(), notes="", user=self.user)

        self.assertEqual(payment.amount, Decimal("1200"))
        self.assertEqual(payment.booking_id, self.booking.id)
        self.assertEqual(PaymentAdvance.objects.get(payment=payment, booking=self.booking).amount, Decimal("200"))
        confirm_payment(payment=payment, user=self.user)
        totals = payment_totals(self.booking)
        self.assertEqual(totals["total_paid"], Decimal("1200"))
        self.assertEqual(totals["outstanding_amount"], Decimal("0"))

    def test_payment_account_is_overdue_when_an_unpaid_installment_is_past_due(self):
        payment = create_payment(booking=self.booking, amount=Decimal("100"), payment_method=Payment.Method.CASH,
                                 transaction_reference="overdue-account", payment_date=date.today(), notes="", user=self.user)
        confirm_payment(payment=payment, user=self.user)
        create_installment(booking=self.booking, installment_number=1, title="Past due", due_date=date.today() - timedelta(days=1), amount=Decimal("500"), notes="")

        self.assertEqual(payment_to_dict(payment)["account_status"], "overdue")

    def test_installment_allocation_and_limits(self):
        payment = create_payment(booking=self.booking, amount=Decimal("500"), payment_method=Payment.Method.UPI, transaction_reference="", payment_date=date.today(), notes="", user=self.user); confirm_payment(payment=payment, user=self.user)
        installment = create_installment(booking=self.booking, installment_number=1, title="First", due_date=date.today() - timedelta(days=1), amount=Decimal("500"), notes="")
        allocate_payment(payment=payment, installment=installment, amount=Decimal("250")); installment.refresh_from_db()
        self.assertEqual(installment.status, Installment.Status.PARTIALLY_PAID)
        allocate_payment(payment=payment, installment=installment, amount=Decimal("250")); installment.refresh_from_db()
        self.assertEqual(installment.status, Installment.Status.PAID)
        with self.assertRaises(ValidationError): allocate_payment(payment=payment, installment=installment, amount=Decimal("1"))

    def test_payment_list_serializer_includes_customer_and_plot_context(self):
        payment = create_payment(booking=self.booking, amount=Decimal("450"), payment_method=Payment.Method.UPI,
                                 transaction_reference="txn-1", payment_date=date.today(), notes="", user=self.user)

        data = payment_to_dict(payment)

        self.assertEqual(data["customer"], {"id": self.booking.lead_id, "name": self.booking.lead.full_name})
        self.assertEqual(data["booking"], {"id": self.booking.id, "plot_number": self.booking.plot.plot_number})
        self.assertEqual(data["plot_number"], self.booking.plot.plot_number)

    def test_payment_list_serializer_includes_refund_reservations(self):
        payment = create_payment(booking=self.booking, amount=Decimal("450"), payment_method=Payment.Method.UPI,
                                 transaction_reference="txn-2", payment_date=date.today(), notes="", user=self.user)
        refund = PaymentRefund.objects.create(
            organization=self.org, payment=payment, amount=Decimal("300"), reason="Customer request",
            refund_date=date.today(), requested_by=self.user,
        )

        data = payment_to_dict(payment)

        self.assertEqual(data["refunds"][0]["id"], refund.id)
        self.assertEqual(data["refunds"][0]["status"], PaymentRefund.Status.PENDING)

    def test_agreement_registry_possession_transitions_and_prerequisites(self):
        with self.assertRaises(ValidationError): create_registry(booking=self.booking)
        agreement = create_agreement(booking=self.booking, created_by=self.user)
        transition_agreement(agreement=agreement, status=Agreement.Status.READY)
        with self.assertRaises(ValidationError): transition_agreement(agreement=agreement, status=Agreement.Status.SIGNED)
        AgreementSignedDocument.objects.create(
            agreement=agreement,
            file=SimpleUploadedFile("signed-agreement.pdf", b"signed copy", content_type="application/pdf"),
            original_filename="signed-agreement.pdf",
            content_type="application/pdf",
            file_size_bytes=len(b"signed copy"),
            uploaded_by=self.user,
        )
        transition_agreement(agreement=agreement, status=Agreement.Status.SIGNED)
        with self.assertRaises(ValidationError): transition_agreement(agreement=agreement, status=Agreement.Status.READY)
        registry = create_registry(booking=self.booking, created_by=self.user)
        with self.assertRaises(ValidationError): transition_registry(registry=registry, status=Registry.Status.COMPLETED)
        registry.registry_date = date.today(); registry.save(update_fields=["registry_date", "updated_at"])
        transition_registry(registry=registry, status=Registry.Status.SCHEDULED)
        transition_registry(registry=registry, status=Registry.Status.COMPLETED)
        possession = create_possession(booking=self.booking, handed_over_by=self.user)
        transition_possession(possession=possession, status=Possession.Status.SCHEDULED)
        transition_possession(possession=possession, status=Possession.Status.COMPLETED)
        possession.refresh_from_db(); self.assertEqual(possession.status, Possession.Status.COMPLETED)
