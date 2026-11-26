from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Customer, Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import CustomerDocument, DocumentCategory


class CustomerDocumentProjectContextTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="documents-admin", is_superuser=True)
        self.organization = Organization.objects.create(name="Documents Org", slug="documents-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project_a = Project.objects.create(organization=self.organization, name="Project A", code="DOC-A")
        self.project_b = Project.objects.create(organization=self.organization, name="Project B", code="DOC-B")
        lead_a = Lead.objects.create(
            organization=self.organization,
            project=self.project_a,
            first_name="Customer",
            last_name="A",
            phone="9000000011",
        )
        lead_b = Lead.objects.create(
            organization=self.organization,
            project=self.project_b,
            first_name="Customer",
            last_name="B",
            phone="9000000012",
        )
        category = DocumentCategory.objects.create(organization=self.organization, name="PAN", code="pan")
        self.customer_a = Customer.objects.create(organization=self.organization, project=self.project_a, lead=lead_a, customer_code="DOC-A-C-000001", full_name="Customer A", phone="9000000011")
        self.customer_b = Customer.objects.create(organization=self.organization, project=self.project_b, lead=lead_b, customer_code="DOC-B-C-000001", full_name="Customer B", phone="9000000012")
        self.document_a = self._document(self.customer_a, category, "a.pdf")
        self.document_b = self._document(self.customer_b, category, "b.pdf")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _document(self, customer, category, filename):
        return CustomerDocument.objects.create(
            organization=self.organization,
            customer=customer,
            document_category=category,
            document_name="PAN",
            file=SimpleUploadedFile(filename, b"document", content_type="application/pdf"),
            file_name=filename,
            file_size=8,
            content_type="application/pdf",
            version=1,
        )

    def test_document_list_is_scoped_to_active_project(self):
        url = "/api/organizations/documents-org/documents/"

        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 400)

        response_a = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual([item["id"] for item in response_a.data["results"]], [self.document_a.id])

        response_b = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_b.id))
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual([item["id"] for item in response_b.data["results"]], [self.document_b.id])

    def test_document_detail_cannot_cross_project_boundary(self):
        url = f"/api/organizations/documents-org/documents/{self.document_b.id}/"
        response = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response.status_code, 404)
