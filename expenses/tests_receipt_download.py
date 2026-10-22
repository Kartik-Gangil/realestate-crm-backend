"""NFR-P12-01 / FR-P16-01 / G-4: receipts are served only through a scoped endpoint."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_PDF
from inventory.models import Project
from organizations.models import Organization, OrganizationMembership
from .models import Expense, ExpenseCategory


class ExpenseReceiptDownloadTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="receipt-owner", email="receipt-owner@example.com", password="pw-123456")
        self.outsider = users.create_user(username="receipt-outsider", email="receipt-outsider@example.com", password="pw-123456")
        organization = Organization.objects.create(name="Receipts", slug="receipts")
        other = Organization.objects.create(name="Receipts other", slug="receipts-other")
        OrganizationMembership.objects.create(organization=organization, user=self.owner, role=OrganizationMembership.Role.ADMIN)
        OrganizationMembership.objects.create(organization=other, user=self.outsider, role=OrganizationMembership.Role.ADMIN)
        self.project = Project.objects.create(organization=organization, name="Main", code="RCP-A")
        self.second_project = Project.objects.create(organization=organization, name="Second", code="RCP-B")
        self.outsider_project = Project.objects.create(organization=other, name="Theirs", code="RCP-X")
        category = ExpenseCategory.objects.create(organization=organization, name="Travel")
        self.expense = Expense.objects.create(organization=organization, project=self.project, submitted_by=self.owner,
                                              category=category, amount="1250.00", description="Taxi",
                                              receipt=SimpleUploadedFile("taxi.pdf", SAMPLE_PDF))
        self.no_receipt = Expense.objects.create(organization=organization, project=self.project, submitted_by=self.owner,
                                                 category=category, amount="10.00", description="Tea")
        self.client = APIClient()

    def get(self, user, project, expense=None):
        self.client.force_authenticate(user)
        return self.client.get(f"/api/expenses/{(expense or self.expense).id}/receipt/", HTTP_X_PROJECT_ID=str(project.id))

    def test_the_receipt_downloads_as_a_protected_attachment(self):
        assert_protected_download(self, self.get(self.owner, self.project), SAMPLE_PDF, "application/pdf")

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get(f"/api/expenses/{self.expense.id}/receipt/").status_code, 401)

    def test_other_organizations_and_projects_get_404(self):
        self.assertEqual(self.get(self.outsider, self.outsider_project).status_code, 404)
        self.assertEqual(self.get(self.owner, self.second_project).status_code, 404)

    def test_an_expense_without_a_receipt_is_404(self):
        self.assertEqual(self.get(self.owner, self.project, self.no_receipt).status_code, 404)

    def test_the_api_returns_the_endpoint_path_never_a_media_url(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/expenses/", HTTP_X_PROJECT_ID=str(self.project.id))
        receipts = {row["id"]: row["receipt"] for row in response.data["data"]["results"]}
        self.assertEqual(receipts, {self.expense.id: f"/api/expenses/{self.expense.id}/receipt/", self.no_receipt.id: None})
        self.assertNotIn("/media/", str(response.data))
