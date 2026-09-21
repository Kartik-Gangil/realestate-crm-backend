from datetime import date, timedelta
from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Agreement, Block, Installment, Payment, Plot, PlotBooking, Possession, Registry, RegistryDocument
from documents.models import CustomerDocument, DocumentCategory
from .phase5_services import (allocate_payment, confirm_payment, create_agreement, create_installment,
    approve_refund, create_payment, create_possession, create_registry, fail_payment, payment_totals, refund_payment,
    transition_agreement, transition_possession, transition_registry)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
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

    def test_installment_allocation_and_limits(self):
        payment = create_payment(booking=self.booking, amount=Decimal("500"), payment_method=Payment.Method.UPI, transaction_reference="", payment_date=date.today(), notes="", user=self.user); confirm_payment(payment=payment, user=self.user)
        installment = create_installment(booking=self.booking, installment_number=1, title="First", due_date=date.today() - timedelta(days=1), amount=Decimal("500"), notes="")
        allocate_payment(payment=payment, installment=installment, amount=Decimal("250")); installment.refresh_from_db()
        self.assertEqual(installment.status, Installment.Status.PARTIALLY_PAID)
        allocate_payment(payment=payment, installment=installment, amount=Decimal("250")); installment.refresh_from_db()
        self.assertEqual(installment.status, Installment.Status.PAID)
        with self.assertRaises(ValidationError): allocate_payment(payment=payment, installment=installment, amount=Decimal("1"))

    def test_agreement_registry_possession_transitions_and_prerequisites(self):
        with self.assertRaises(ValidationError): create_registry(booking=self.booking)
        agreement = create_agreement(booking=self.booking, created_by=self.user)
        transition_agreement(agreement=agreement, status=Agreement.Status.READY)
        transition_agreement(agreement=agreement, status=Agreement.Status.SIGNED)
        with self.assertRaises(ValidationError): transition_agreement(agreement=agreement, status=Agreement.Status.READY)
        Payment.objects.create(organization=self.org, booking=self.booking, payment_id="P5-REG-PAID", amount=Decimal("1000"), payment_method=Payment.Method.CASH, status=Payment.Status.SUCCESS, payment_date=date.today(), received_by=self.user)
        registry = create_registry(booking=self.booking, created_by=self.user)
        category = DocumentCategory.objects.create(organization=self.org, name="PAN", code="pan")
        document = CustomerDocument.objects.create(organization=self.org, customer=self.booking.lead, document_category=category, document_name="PAN", file=SimpleUploadedFile("pan.pdf", b"%PDF-1.4 valid", content_type="application/pdf"), file_name="pan.pdf", file_size=14, content_type="application/pdf", version=1, status=CustomerDocument.Status.VERIFIED)
        RegistryDocument.objects.create(registry=registry, organization=self.org, customer_document=document, document_label="PAN")
        with self.assertRaises(ValidationError): transition_registry(registry=registry, status=Registry.Status.COMPLETED)
        registry.registry_date = date.today(); registry.save(update_fields=["registry_date", "updated_at"])
        transition_registry(registry=registry, status=Registry.Status.SCHEDULED)
        transition_registry(registry=registry, status=Registry.Status.COMPLETED)
        possession = create_possession(booking=self.booking, handed_over_by=self.user)
        transition_possession(possession=possession, status=Possession.Status.SCHEDULED)
        transition_possession(possession=possession, status=Possession.Status.COMPLETED)
        possession.refresh_from_db(); self.assertEqual(possession.status, Possession.Status.COMPLETED)
