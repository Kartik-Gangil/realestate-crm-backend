"""NFR-P12-01 / G-4: registry documents download through a scoped endpoint (the route the frontend calls)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_JPEG, SAMPLE_PDF
from documents.models import CustomerDocument, DocumentCategory
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership
from .models import Block, Customer, Plot, PlotBooking, Project, Registry, RegistryDocument


class RegistryDocumentDownloadTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="registry-download-admin", password="pw-123456")
        self.organization = Organization.objects.create(name="Registry downloads", slug="registry-downloads")
        OrganizationMembership.objects.create(organization=self.organization, user=user, role=OrganizationMembership.Role.ADMIN)
        self.project = Project.objects.create(organization=self.organization, name="A", code="RD-A")
        self.other_project = Project.objects.create(organization=self.organization, name="B", code="RD-B")
        block = Block.objects.create(organization=self.organization, project=self.project, name="Block A", code="A")
        plot = Plot.objects.create(organization=self.organization, project=self.project, block=block, plot_number="A-001",
                                   size=Decimal("100"), total_price=Decimal("100000"), status=Plot.Status.BOOKED)
        self.lead = Lead.objects.create(organization=self.organization, project=self.project, first_name="Buyer", phone="9000000041")
        self.customer = Customer.objects.create(organization=self.organization, project=self.project, lead=self.lead, customer_code="RD-A-C-000001", full_name="Buyer", phone="9000000041")
        booking = PlotBooking.objects.create(organization=self.organization, project=self.project, customer=self.customer, lead=self.lead, plot=plot,
                                             status=PlotBooking.Status.CONFIRMED, final_price=Decimal("100000"))
        self.registry = Registry.objects.create(organization=self.organization, booking=booking, registry_number="REG-D1",
                                                consideration_amount=Decimal("100000"))
        self.uploaded = RegistryDocument.objects.create(registry=self.registry, file=SimpleUploadedFile("deed.pdf", SAMPLE_PDF),
                                                        document_label="Deed", original_filename="deed.pdf",
                                                        content_type="application/pdf", file_size_bytes=len(SAMPLE_PDF))
        category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")
        customer_document = CustomerDocument.objects.create(
            organization=self.organization, customer=self.customer, document_category=category, document_name="PAN",
            file=SimpleUploadedFile("pan.jpg", SAMPLE_JPEG), file_name="pan.jpg", file_size=len(SAMPLE_JPEG),
            content_type="image/jpeg", version=1)
        self.reference = RegistryDocument.objects.create(registry=self.registry, customer_document=customer_document, document_label="PAN")
        self.client = APIClient()
        self.client.force_authenticate(user)

    def url(self, document):
        return f"/api/organizations/registry-downloads/registries/{self.registry.id}/documents/{document.id}/download/"

    def test_an_uploaded_document_downloads_as_a_protected_attachment(self):
        response = self.client.get(self.url(self.uploaded), HTTP_X_PROJECT_ID=str(self.project.id))
        assert_protected_download(self, response, SAMPLE_PDF, "application/pdf")
        self.assertIn("deed.pdf", response["Content-Disposition"])

    def test_a_referenced_customer_document_serves_that_file(self):
        response = self.client.get(self.url(self.reference), HTTP_X_PROJECT_ID=str(self.project.id))
        assert_protected_download(self, response, SAMPLE_JPEG, "image/jpeg")

    def test_authentication_and_project_scoping(self):
        self.assertEqual(self.client.get(self.url(self.uploaded), HTTP_X_PROJECT_ID=str(self.other_project.id)).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url(self.uploaded), HTTP_X_PROJECT_ID=str(self.project.id)).status_code, 401)

    def test_the_listing_includes_the_download_path(self):
        listing = self.client.get(f"/api/organizations/registry-downloads/registries/{self.registry.id}/documents/",
                                  HTTP_X_PROJECT_ID=str(self.project.id))
        paths = {row["id"]: row["download_url"] for row in listing.data["results"]}
        self.assertEqual(paths, {document.id: self.url(document) for document in (self.uploaded, self.reference)})
