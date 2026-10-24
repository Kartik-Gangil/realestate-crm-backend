from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Block, Payment, PaymentReceipt, Plot, PlotBooking, Project


class PaymentReceiptDownloadTests(TestCase):
    """FR-P11-07 / FR-P11-08 receipt download contract tests."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="accounts@example.com",
            email="accounts@example.com",
            password="password123",
        )
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Green Acres",
            code="GA",
        )
        block = Block.objects.create(
            organization=self.organization,
            project=self.project,
            name="A Block",
            code="A",
        )
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=block,
            plot_number="A-101",
            size=Decimal("100.00"),
            total_price=Decimal("500000.00"),
            status=Plot.Status.BOOKED,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Ada",
            last_name="Lovelace",
            phone="9876543210",
        )
        booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=lead,
            plot=plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("500000.00"),
            created_by=self.user,
        )
        payment = Payment.objects.create(
            organization=self.organization,
            booking=booking,
            payment_id="PAY-20261022-RECEIPT",
            amount=Decimal("125000.00"),
            payment_method=Payment.Method.UPI,
            status=Payment.Status.SUCCESS,
            transaction_reference="UPI-12345",
            payment_date=date(2026, 10, 22),
            received_by=self.user,
        )
        self.receipt = PaymentReceipt.objects.create(
            organization=self.organization,
            payment=payment,
            receipt_number="RCT-ACME-00000001",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.defaults["HTTP_X_PROJECT_ID"] = str(self.project.id)

    def test_receipt_download_returns_a_real_pdf(self):
        response = self.client.get(
            reverse(
                "inventory:managed-payment-receipt",
                args=[self.organization.slug, self.receipt.payment_id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertTrue(response.content.rstrip().endswith(b"%%EOF"))
        self.assertIn(self.receipt.receipt_number.encode(), response.content)
        self.assertIn(b"INR 125,000.00", response.content)
        self.assertIn(
            'attachment; filename="Receipt_RCT-ACME-00000001.pdf"',
            response["Content-Disposition"],
        )
