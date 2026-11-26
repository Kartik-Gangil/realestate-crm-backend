"""Attached UAT report regressions for LC-04."""

from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project

from .models import Expense, ExpenseCategory


class UatLcExpenseSubmissionTests(TestCase):
    """FR-P16-02/FR-P16-06/API-P16-01 [LC-04]."""

    def setUp(self):
        self.organization = make_organization("uat-lc-04")
        self.project = make_project(self.organization, "LC04")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.category = ExpenseCategory.objects.create(
            organization=self.organization,
            project=self.project,
            name="UAT travel",
        )

    def test_manager_can_submit_own_claim_into_pending_approval(self):
        client = APIClient()
        client.force_authenticate(self.manager.user)

        response = client.post(
            "/api/v1/expenses/",
            {
                "category_id": self.category.pk,
                "amount": "1250.00",
                "date": "2026-11-26",
                "description": "UAT travel claim",
                "action": "submit",
            },
            format="json",
            HTTP_X_PROJECT_ID=str(self.project.pk),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["status"], Expense.Status.PENDING_APPROVAL)
