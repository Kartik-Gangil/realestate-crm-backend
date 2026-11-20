from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from expenses.models import Expense, ExpenseCategory
from expenses.serializers import ExpenseSerializer


class BackfillProjectDefaultsTests(TestCase):
    """G-1 items 4-5, GNFR-06, FR-P16-01: backfill reuses names and remaps expenses."""

    def setUp(self):
        self.organization = make_organization("backfill-org")
        self.project = make_project(self.organization, "BACKFILL")
        membership = make_member(self.organization, role="admin", projects=[self.project])
        self.user = membership.user
        self.default_category = ExpenseCategory.objects.create(
            organization=self.organization, name="Travel", description="Template"
        )
        self.project_category = ExpenseCategory.objects.create(
            organization=self.organization, project=self.project, name="Travel", description="Existing copy"
        )
        ExpenseCategory.objects.create(
            organization=self.organization, name="Office", description="Template office"
        )
        self.expense = Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=self.user,
            category=self.default_category,
            amount=Decimal("100.00"),
            description="Old expense",
        )

    def test_backfill_reuses_categories_remaps_expenses_and_keeps_templates_g1_item_4_fr_p16_01(self):
        call_command("backfill_project_defaults", "--apply", stdout=StringIO())

        self.expense.refresh_from_db()
        self.assertEqual(self.expense.category_id, self.project_category.id)
        self.assertEqual(
            set(ExpenseCategory.objects.filter(project=self.project).values_list("name", flat=True)),
            {"Travel", "Office"},
        )
        self.assertEqual(
            ExpenseCategory.objects.filter(organization=self.organization, project__isnull=True).count(), 2
        )
        serializer = ExpenseSerializer(
            self.expense,
            data={"description": "Edited without changing category"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            "/api/categories/", **project_request_kwargs(self.project)
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {item["name"] for item in response.data["data"]}, {"Travel", "Office"}
        )
