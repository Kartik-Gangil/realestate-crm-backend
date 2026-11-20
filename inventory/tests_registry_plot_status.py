from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.models import CustomerDocument, DocumentCategory
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Agreement, AgreementSignedDocument, Block, Payment, PaymentAllocation, Plot, PlotBooking, Project, Registry
from .phase5_services import transition_registry


class RegistryPlotStatusTests(TestCase):
    """FR-P13-01/FR-P8-02/API-P13-03 registry completion behavior."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="registry-admin", password="password123")
        self.organization = Organization.objects.create(name="Registry Org", slug="registry-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        project = Project.objects.create(organization=self.organization, name="Registry Project", code="REG")
        block = Block.objects.create(organization=self.organization, project=project, name="Block A", code="A")
        plot = Plot.objects.create(
            organization=self.organization,
            project=project,
            block=block,
            plot_number="A-001",
            size=Decimal("100.00"),
            total_price=Decimal("1000.00"),
            status=Plot.Status.BOOKED,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            project=project,
            first_name="Registry",
            last_name="Buyer",
            phone="9000000001",
        )
        booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=lead,
            plot=plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("1000.00"),
            created_by=self.user,
        )
        identity_category = DocumentCategory.objects.create(
            organization=self.organization, name="Identity", code="identity"
        )
        CustomerDocument.objects.create(
            organization=self.organization,
            customer=lead,
            document_category=identity_category,
            document_name="Identity",
            file=SimpleUploadedFile("identity.pdf", b"verified identity", content_type="application/pdf"),
            file_name="identity.pdf",
            file_size=len(b"verified identity"),
            content_type="application/pdf",
            version=1,
            status=CustomerDocument.Status.VERIFIED,
            verified_by=self.user,
        )
        agreement = Agreement.objects.create(
            organization=self.organization,
            booking=booking,
            status=Agreement.Status.SIGNED,
            created_by=self.user,
        )
        AgreementSignedDocument.objects.create(
            agreement=agreement,
            file=SimpleUploadedFile("signed.pdf", b"signed agreement", content_type="application/pdf"),
            original_filename="signed.pdf",
            content_type="application/pdf",
            file_size_bytes=len(b"signed agreement"),
            uploaded_by=self.user,
        )
        payment = Payment.objects.create(
            organization=self.organization,
            booking=booking,
            payment_id="REG-TEST-1",
            amount=Decimal("1000.00"),
            payment_method=Payment.Method.CASH,
            status=Payment.Status.SUCCESS,
            payment_date=date.today(),
            received_by=self.user,
        )
        PaymentAllocation.objects.create(payment=payment, booking=booking, amount=Decimal("1000.00"))
        self.plot = plot
        self.registry = Registry.objects.create(
            organization=self.organization,
            booking=booking,
            registry_date=date.today(),
            status=Registry.Status.IN_PROCESS,
            created_by=self.user,
        )

    def test_completed_registry_marks_linked_plot_sold(self):
        transition_registry(
            registry=self.registry,
            status=Registry.Status.COMPLETED,
            user=self.user,
        )

        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, Plot.Status.SOLD)
