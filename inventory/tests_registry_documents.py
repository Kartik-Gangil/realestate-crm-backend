from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership
from core.tests.samples import FORGED_EXE, FORGED_HTML, SAMPLE_JPEG, SAMPLE_PDF
from documents.models import CustomerDocument, DocumentCategory

from .models import Block, Plot, PlotBooking, Project, Registry


class RegistryDocumentApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="registry-doc-admin", is_superuser=True)
        self.organization = Organization.objects.create(name="Registry Docs Org", slug="registry-docs-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project = Project.objects.create(organization=self.organization, name="Project A", code="REG-A")
        block = Block.objects.create(organization=self.organization, project=self.project, name="Block A", code="A")
        plot = Plot.objects.create(
            organization=self.organization,
            project=self.project,
            block=block,
            plot_number="A-001",
            size=Decimal("100"),
            total_price=Decimal("100000"),
            status=Plot.Status.BOOKED,
        )
        lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Buyer",
            last_name="A",
            phone="9000000011",
        )
        booking = PlotBooking.objects.create(
            organization=self.organization,
            lead=lead,
            plot=plot,
            status=PlotBooking.Status.CONFIRMED,
            final_price=Decimal("100000"),
        )
        self.registry = Registry.objects.create(
            organization=self.organization,
            booking=booking,
            registry_number="REG-1",
            consideration_amount=Decimal("100000"),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.defaults["HTTP_X_PROJECT_ID"] = str(self.project.id)

    def documents_url(self):
        return f"/api/organizations/{self.organization.slug}/registries/{self.registry.id}/documents/"

    def post_file(self, name, content, **extra):
        data = {"file": SimpleUploadedFile(name, content, content_type="application/pdf"), "document_label": "Deed", **extra}
        return self.client.post(self.documents_url(), data, format="multipart")

    def test_registry_document_upload_is_listed(self):
        response = self.client.post(
            self.documents_url(),
            {
                "file": SimpleUploadedFile("sale-deed.pdf", SAMPLE_PDF, content_type="application/pdf"),
                "document_label": "Signed Sale Deed",
                "document_type": "sale_deed",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["document_label"], "Signed Sale Deed")

        listing = self.client.get(self.documents_url())
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["document_label"], "Signed Sale Deed")

    def test_registry_response_contains_booking_display_data(self):
        response = self.client.get(
            f"/api/organizations/{self.organization.slug}/registries/{self.registry.id}/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["buyer_name"], "Buyer A")
        self.assertEqual(response.data["plot_number"], "A-001")
        self.assertEqual(response.data["block_name"], "Block A")
        self.assertEqual(response.data["consideration_amount"], "100000.00")

    def test_forged_registry_document_is_rejected_task_sec_001(self):
        for name, content in (("deed.pdf", FORGED_HTML), ("deed.png", FORGED_EXE)):
            response = self.post_file(name, content)
            self.assertEqual(response.status_code, 400)
            self.assertIn("file", response.data)
        self.assertEqual(self.client.get(self.documents_url()).data["count"], 0)

    def test_registry_document_stores_the_detected_type_task_sec_001(self):
        response = self.post_file("deed.pdf", SAMPLE_JPEG)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["content_type"], "image/jpeg")

    def test_a_file_sent_with_a_customer_document_is_still_checked_task_sec_001(self):
        category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")
        customer_document = CustomerDocument.objects.create(organization=self.organization, customer=self.registry.booking.lead, document_category=category, document_name="PAN", file=SimpleUploadedFile("pan.pdf", SAMPLE_PDF), file_name="pan.pdf", file_size=len(SAMPLE_PDF), content_type="application/pdf", version=1)
        response = self.post_file("deed.pdf", FORGED_HTML, customer_document_id=customer_document.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)
