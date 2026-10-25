from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from unittest.mock import patch
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inventory.models import Project
from core.tests.samples import FORGED_EXE, FORGED_HTML
from expenses.models import Expense, ExpenseCategory
from .models import Organization, OrganizationMembership, OrganizationRole, Permission


class ExpenseCategoryApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username="expense-admin", email="expense-admin@example.com", password="password123")
        self.viewer = user_model.objects.create_user(username="expense-viewer", email="expense-viewer@example.com", password="password123")
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Main project", code="MAIN")
        admin_role = OrganizationRole.objects.create(organization=self.org, name="Expense admin", code="expense-admin")
        viewer_role = OrganizationRole.objects.create(organization=self.org, name="Expense viewer", code="expense-viewer")
        add_permission, _ = Permission.objects.get_or_create(module="expenses", action="add", defaults={"name": "Add expenses"})
        edit_permission, _ = Permission.objects.get_or_create(module="expenses", action="edit", defaults={"name": "Edit expenses"})
        admin_role.permissions.set([add_permission, edit_permission])
        OrganizationMembership.objects.create(organization=self.org, user=self.admin, role="admin", organization_role=admin_role)
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role="telecaller", organization_role=viewer_role)
        self.category = ExpenseCategory.objects.create(organization=self.org, name="Travel", description="Travel costs")
        self.category_id = self.category.id
        self.client = APIClient()

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}", HTTP_X_PROJECT_ID=str(self.project.id))

    def test_lists_categories_for_active_project_organization(self):
        self.authenticate(self.viewer)

        response = self.client.get("/api/categories/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"][0]["name"], "Travel")

    def test_admin_can_create_and_edit_category(self):
        self.authenticate(self.admin)

        created = self.client.post("/api/categories/", {"name": "Office", "description": "Office supplies"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["name"], "Office")

        category_id = created.data["data"]["id"]
        updated = self.client.patch(f"/api/categories/{category_id}/", {"name": "Office supplies"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["name"], "Office supplies")

    def test_category_mutation_requires_expense_permission(self):
        self.authenticate(self.viewer)

        response = self.client.post("/api/categories/", {"name": "Restricted"}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_receipt_download_requires_expense_visibility_permission(self):
        expense = Expense.objects.create(
            organization=self.org,
            project=self.project,
            submitted_by=self.admin,
            category=self.category,
            amount="125.00",
            description="Restricted receipt",
        )
        self.authenticate(self.viewer)

        response = self.client.get(f"/api/expenses/{expense.id}/receipt/")

        self.assertEqual(response.status_code, 403)

    def test_expense_categories_are_available_in_django_admin(self):
        self.assertIn(ExpenseCategory, admin.site._registry)

    @override_settings(MEDIA_ROOT="C:/Users/Public/realestate-crm-test-media")
    @patch("django.core.files.storage.FileSystemStorage._save", return_value="expenses/acme/taxi.pdf")
    def test_user_can_log_a_draft_expense_with_a_receipt(self, _save):
        self.authenticate(self.admin)
        receipt = SimpleUploadedFile("taxi.pdf", b"%PDF-1.4 receipt", content_type="application/pdf")

        response = self.client.post("/api/expenses/", {
            "date": "2026-09-28", "category": self.category_id, "amount": "1250.00",
            "description": "Taxi to client", "action": "draft", "receipt": receipt,
        }, format="multipart")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], "draft")
        self.assertEqual(response.data["data"]["receipt"], f"/api/expenses/{response.data['data']['id']}/receipt/")
        self.assertTrue(Expense.objects.filter(description="Taxi to client").exists())

    def test_task_p16_001_submission_without_receipt_above_threshold_is_allowed(self):
        self.authenticate(self.admin)

        response = self.client.post("/api/expenses/", {
            "date": "2026-09-28", "category": self.category_id, "amount": "6000.00",
            "description": "Office equipment", "action": "submit",
        }, format="multipart")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], "pending_approval")

    def test_forged_receipt_is_rejected_task_sec_001(self):
        self.authenticate(self.admin)
        for name, content in (("taxi.pdf", FORGED_HTML), ("taxi.png", FORGED_EXE)):
            response = self.client.post("/api/expenses/", {
                "date": "2026-09-28", "category": self.category_id, "amount": "1250.00", "description": "Forged receipt",
                "action": "draft", "receipt": SimpleUploadedFile(name, content, content_type="application/pdf"),
            }, format="multipart")
            self.assertEqual(response.status_code, 400)
            self.assertIn("receipt", response.data)
        self.assertFalse(Expense.objects.filter(description="Forged receipt").exists())
