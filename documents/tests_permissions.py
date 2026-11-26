from rest_framework.test import APITestCase

from core.tests.factories import make_lead, make_member, make_organization, make_project
from inventory.customer_services import create_customer
from leads.models import Lead
from organizations.models import Permission

from .models import CustomerDocument, DocumentCategory


class DocumentPermissionEnforcementTests(APITestCase):
    """Task 4 / GNFR-05: document access must be denied after RBAC revocation."""

    def setUp(self):
        self.organization = make_organization("acme")
        self.project = make_project(self.organization, "MAIN")
        membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.user = membership.user
        self.role = membership.organization_role
        self.documents_view, _ = Permission.objects.get_or_create(
            module="documents",
            action="view",
            defaults={"name": "View documents"},
        )
        lead = make_lead(self.organization, self.project, first_name="Customer")
        self.customer = create_customer(organization=self.organization, project=self.project, lead=lead, full_name="Customer", phone="9000000121")
        self.category = DocumentCategory.objects.create(
            organization=self.organization,
            name="Identity",
            code="identity",
        )
        self.document = CustomerDocument.objects.create(
            organization=self.organization,
            customer=self.customer,
            document_category=self.category,
            document_name="Identity",
            file="blocked/identity.pdf",
            file_name="identity.pdf",
            file_size=10,
            content_type="application/pdf",
            version=1,
            uploaded_by=self.user,
        )
        self.client.force_authenticate(self.user)

    def url(self, path):
        return f"/api/organizations/acme/{path}"

    def test_document_view_permission_is_required_for_lists_and_preview(self):
        self.role.permissions.add(self.documents_view)
        self.assertEqual(
            self.client.get(self.url("documents/"), HTTP_X_PROJECT_ID=str(self.project.id)).status_code,
            200,
        )
        self.role.permissions.remove(self.documents_view)

        self.assertEqual(
            self.client.get(self.url("documents/"), HTTP_X_PROJECT_ID=str(self.project.id)).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                self.url(f"documents/{self.document.id}/download/"),
                HTTP_X_PROJECT_ID=str(self.project.id),
            ).status_code,
            403,
        )

    def test_customer_documents_read_requires_documents_view_permission(self):
        response = self.client.get(
            self.url(f"customers/{self.customer.id}/documents/"),
            HTTP_X_PROJECT_ID=str(self.project.id),
        )
        self.assertEqual(response.status_code, 403)

    def test_document_requirements_read_requires_documents_view_permission(self):
        response = self.client.get(
            self.url(f"customers/{self.customer.id}/document-requirements/"),
            HTTP_X_PROJECT_ID=str(self.project.id),
        )
        self.assertEqual(response.status_code, 403)
