"""Owner-approved Phase 17 dashboard aggregate coverage [UAT-D17]."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Payment
from leads.models import Lead
from core.tests.factories import make_lead, make_member, make_organization, make_project


class UatD17DashboardAggregateTests(TestCase):
    def setUp(self):
        self.organization = make_organization("uat-d17-org")
        self.project = make_project(self.organization, "D17")
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.lead = make_lead(self.organization, self.project, first_name="D17 Lead")
        Payment.objects.create(
            organization=self.organization,
            amount=Decimal("125.50"),
            payment_method="cash",
            status=Payment.Status.SUCCESS,
            payment_date=date.today(),
        )
        self.client = APIClient()

    def _url(self):
        return f"/api/v1/dashboards/admin/?organization={self.organization.slug}"

    def test_admin_receives_org_aggregate_using_decimal_revenue(self):
        self.client.force_authenticate(self.admin_membership.user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data.get("data", response.data)
        self.assertEqual(payload["total_leads"], 1)
        self.assertEqual(payload["active_projects"], 1)
        self.assertEqual(Decimal(payload["total_revenue"]), Decimal("125.50"))

    def test_non_admin_cannot_read_org_aggregate(self):
        self.client.force_authenticate(self.manager_membership.user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
