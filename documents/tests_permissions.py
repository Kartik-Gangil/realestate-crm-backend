from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from inventory.models import Project
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership, OrganizationRole, Permission

from .models import CustomerDocument, DocumentCategory


class DocumentPermissionEnforcementTests(APITestCase):
    """Task 4 / GNFR-05: document access must be denied after RBAC revocation."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="telecaller",
            email="telecaller@example.com",
            password="password123",
        )
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(
            organization=self.organization,
            name="Main project",
            code="MAIN",
        )
        self.role = OrganizationRole.objects.create(
            organization=self.organization,
            name="Telecaller",
            code="telecaller",
        )
        self.documents_view, _ = Permission.objects.get_or_create(
            module="documents",
            action="view",
            defaults={"name": "View documents"},
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.TELECALLER,
            organization_role=self.role,
        )
        self.customer = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Customer",
            phone="1",
        )
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

    def test_document_and_kyc_related_reads_are_denied_without_view_permission(self):
        for path in (
            "documents/categories/",
            f"customers/{self.customer.id}/documents/",
            f"customers/{self.customer.id}/document-requirements/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(self.url(path), HTTP_X_PROJECT_ID=str(self.project.id)).status_code,
                    403,
                )
