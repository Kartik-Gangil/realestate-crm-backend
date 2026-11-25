"""FR-P16-06 [UAT-D21] expense claim ownership acceptance tests."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project
from .models import Expense, ExpenseCategory


class UatD21ExpenseOwnershipTests(TestCase):
    def setUp(self):
        self.organization = make_organization("uat-d21-expenses")
        self.project = make_project(self.organization, "D21")
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.other_manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.employee_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.accounts_membership = make_member(self.organization, role="accounts", projects=[self.project])
        self.employee_membership.reporting_manager = self.manager_membership
        self.employee_membership.save(update_fields=["reporting_manager"])
        self.category = ExpenseCategory.objects.create(
            organization=self.organization,
            project=self.project,
            name="UAT travel",
        )
        self.headers = {"HTTP_X_PROJECT_ID": str(self.project.pk)}

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def _expense(self, submitter):
        return Expense.objects.create(
            organization=self.organization,
            project=self.project,
            submitted_by=submitter,
            category=self.category,
            amount=Decimal("1250.00"),
            description="UAT D21 expense",
            status=Expense.Status.PENDING_APPROVAL,
        )

    def _action_url(self, expense, action):
        return f"/api/v1/expenses/{expense.pk}/{action}/"

    def test_manager_approves_or_rejects_team_claims_but_not_other_teams_or_own_claim(self):
        team_claim = self._expense(self.employee_membership.user)
        approved = self._client(self.manager_membership.user).post(
            self._action_url(team_claim, "approve"), {}, format="json", **self.headers
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        other_team_claim = self._expense(self.other_manager_membership.user)
        denied_other_team = self._client(self.manager_membership.user).post(
            self._action_url(other_team_claim, "approve"), {}, format="json", **self.headers
        )
        self.assertEqual(denied_other_team.status_code, 403, denied_other_team.data)

        own_claim = self._expense(self.manager_membership.user)
        denied_own_approval = self._client(self.manager_membership.user).post(
            self._action_url(own_claim, "approve"), {}, format="json", **self.headers
        )
        denied_own_rejection = self._client(self.manager_membership.user).post(
            self._action_url(own_claim, "reject"), {"reason": "Not self-approved"}, format="json", **self.headers
        )
        self.assertEqual(denied_own_approval.status_code, 403, denied_own_approval.data)
        self.assertEqual(denied_own_rejection.status_code, 403, denied_own_rejection.data)

    def test_admin_approves_a_managers_own_claim_and_accounts_reimburses(self):
        own_claim = self._expense(self.manager_membership.user)
        approved = self._client(self.admin_membership.user).post(
            self._action_url(own_claim, "approve"), {}, format="json", **self.headers
        )
        self.assertEqual(approved.status_code, 200, approved.data)

        reimbursed = self._client(self.accounts_membership.user).post(
            self._action_url(own_claim, "reimburse"),
            {"transaction_reference": "UAT-D21-TXN-001"},
            format="json",
            **self.headers,
        )
        self.assertEqual(reimbursed.status_code, 200, reimbursed.data)
        self.assertEqual(reimbursed.data["data"]["status"], Expense.Status.REIMBURSED)
