from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from unittest.mock import patch
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from core.tests.samples import FORGED_EXE, FORGED_HTML
from expenses.models import Expense, ExpenseCategory
from .models import OrganizationMembership, OrganizationRole, Permission, ProjectAssignment


class ExpenseCategoryApiTests(TestCase):
    def setUp(self):
        self.org = make_organization("acme")
        self.project = make_project(self.org, "MAIN")
        admin_member = make_member(self.org, role="admin", projects=[self.project])
        viewer_member = make_member(self.org, role="telecaller", projects=[self.project])
        self.admin = admin_member.user
        self.viewer = viewer_member.user
        admin_role = OrganizationRole.objects.create(organization=self.org, name="Expense admin", code="expense-admin")
        viewer_role = OrganizationRole.objects.create(organization=self.org, name="Expense viewer", code="expense-viewer")
        add_permission, _ = Permission.objects.get_or_create(module="expenses", action="add", defaults={"name": "Add expenses"})
        edit_permission, _ = Permission.objects.get_or_create(module="expenses", action="edit", defaults={"name": "Edit expenses"})
        admin_role.permissions.set([add_permission, edit_permission])
        admin_member.organization_role = admin_role
        admin_member.save(update_fields=["organization_role"])
        viewer_member.organization_role = viewer_role
        viewer_member.save(update_fields=["organization_role"])
        ProjectAssignment.objects.filter(membership=admin_member, project=self.project).update(role=admin_role)
        ProjectAssignment.objects.filter(membership=viewer_member, project=self.project).update(role=viewer_role)
        self.category = ExpenseCategory.objects.create(organization=self.org, project=self.project, name="Travel", description="Travel costs")
        self.category_id = self.category.id
        self.client = APIClient()

    def authenticate(self, user):
        self.client.force_authenticate(user)

    def headers(self):
        return project_request_kwargs(self.project)

    def test_lists_categories_for_active_project_organization(self):
        self.authenticate(self.viewer)

        response = self.client.get("/api/categories/", **self.headers())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"][0]["name"], "Travel")

    def test_admin_can_create_and_edit_category(self):
        self.authenticate(self.admin)

        created = self.client.post("/api/categories/", {"name": "Office", "description": "Office supplies"}, format="json", **self.headers())
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["data"]["name"], "Office")

        category_id = created.data["data"]["id"]
        updated = self.client.patch(f"/api/categories/{category_id}/", {"name": "Office supplies"}, format="json", **self.headers())
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["data"]["name"], "Office supplies")

    def test_category_mutation_requires_expense_permission(self):
        self.authenticate(self.viewer)

        response = self.client.post("/api/categories/", {"name": "Restricted"}, format="json", **self.headers())

        self.assertEqual(response.status_code, 403)

    def test_empty_pending_approval_queue_returns_forbidden_without_raising(self):
        self.authenticate(self.viewer)

        response = self.client.get("/api/expenses/pending-approval/", **self.headers())

        self.assertEqual(response.status_code, 403, response.data)

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

        response = self.client.get(f"/api/expenses/{expense.id}/receipt/", **self.headers())

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
        }, format="multipart", **self.headers())

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], "draft")
        self.assertEqual(response.data["data"]["receipt"], f"/api/expenses/{response.data['data']['id']}/receipt/")
        self.assertTrue(Expense.objects.filter(description="Taxi to client").exists())

    def test_task_p16_001_submission_without_receipt_above_threshold_is_allowed(self):
        self.authenticate(self.admin)

        response = self.client.post("/api/expenses/", {
            "date": "2026-09-28", "category": self.category_id, "amount": "6000.00",
            "description": "Office equipment", "action": "submit",
        }, format="multipart", **self.headers())

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], "pending_approval")

    def test_forged_receipt_is_rejected_task_sec_001(self):
        self.authenticate(self.admin)
        for name, content in (("taxi.pdf", FORGED_HTML), ("taxi.png", FORGED_EXE)):
            response = self.client.post("/api/expenses/", {
                "date": "2026-09-28", "category": self.category_id, "amount": "1250.00", "description": "Forged receipt",
                "action": "draft", "receipt": SimpleUploadedFile(name, content, content_type="application/pdf"),
            }, format="multipart", **self.headers())
            self.assertEqual(response.status_code, 400)
            self.assertIn("receipt", response.data)
        self.assertFalse(Expense.objects.filter(description="Forged receipt").exists())
