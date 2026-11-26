"""NFR-P12-01 / G-4: downloads are protected attachments typed by bytes."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.samples import FORGED_HTML, SAMPLE_PDF
from inventory.models import Customer, Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership
from .models import CustomerDocument, DocumentCategory, EmployeeDocument, EmployeeDocumentCategory


class DocumentDownloadTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="downloads-admin", is_superuser=True)
        self.organization = Organization.objects.create(name="Downloads Org", slug="downloads-org")
        self.membership = OrganizationMembership.objects.create(organization=self.organization, user=user, role=OrganizationMembership.Role.ADMIN)
        project = Project.objects.create(organization=self.organization, name="Project A", code="DL-A")
        lead = Lead.objects.create(organization=self.organization, project=project, first_name="Customer", phone="9000000021")
        self.customer = Customer.objects.create(organization=self.organization, project=project, lead=lead, customer_code="DL-A-C-000001", full_name="Customer", phone="9000000021")
        self.category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")
        self.client = APIClient()
        self.client.force_authenticate(user)
        self.client.defaults["HTTP_X_PROJECT_ID"] = str(project.id)

    def customer_document(self, content, stored_type):
        return CustomerDocument.objects.create(organization=self.organization, customer=self.customer, document_category=self.category, document_name="PAN", file=SimpleUploadedFile("pan.pdf", content), file_name="pan.pdf", file_size=len(content), content_type=stored_type, version=1)

    def download(self, path):
        return self.client.get(f"/api/organizations/downloads-org/{path}/download/")

    def assert_protected_attachment(self, response, content, content_type):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)
        self.assertEqual(response["Content-Type"], content_type)
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_customer_document_download(self):
        document = self.customer_document(SAMPLE_PDF, "application/pdf")
        self.assert_protected_attachment(self.download(f"documents/{document.id}"), SAMPLE_PDF, "application/pdf")

    def test_the_stored_type_is_never_trusted(self):
        document = self.customer_document(FORGED_HTML, "text/html")
        self.assert_protected_attachment(self.download(f"documents/{document.id}"), FORGED_HTML, "application/octet-stream")

    def test_employee_document_download(self):
        category = EmployeeDocumentCategory.objects.create(organization=self.organization, name="Offer letter", code="offer")
        document = EmployeeDocument.objects.create(organization=self.organization, employee=self.membership, document_category=category, document_name="Offer", file=SimpleUploadedFile("offer.pdf", SAMPLE_PDF), file_name="offer.pdf", file_size=len(SAMPLE_PDF), content_type="application/pdf", version=1)
        self.assert_protected_attachment(self.download(f"employee-documents/{document.id}"), SAMPLE_PDF, "application/pdf")

    def test_download_requires_authentication(self):
        document = self.customer_document(SAMPLE_PDF, "application/pdf")
        self.client.force_authenticate(None)
        self.assertEqual(self.download(f"documents/{document.id}").status_code, 401)
