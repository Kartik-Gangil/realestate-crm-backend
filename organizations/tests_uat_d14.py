"""FR-P15-03 [UAT-D14] leave-date validation acceptance tests."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .hr_services import ensure_leave_balance
from .models import Organization, OrganizationMembership, Permission


class UatD14LeaveDateTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="UAT-D14 org", slug="uat-d14-org")
        self.employee = get_user_model().objects.create_user(
            username="employee@uat-d14.test",
            email="employee@uat-d14.test",
            password="Employee123!",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.employee,
            role="telecaller",
            employee_id="EMP0001",
        )
        permissions = []
        for code in ("leave.view", "leave.add"):
            module, action = code.split(".")
            permission, _ = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={"name": code},
            )
            permissions.append(permission)
        self.membership.organization_role.permissions.add(*permissions)
        self.client = APIClient()
        self.client.force_authenticate(self.employee)
        self.url = f"/api/v1/organizations/{self.organization.slug}/leaves/"
        self.today = timezone.localdate()
        balance = ensure_leave_balance(
            organization=self.organization,
            employee=self.membership,
            leave_type="casual",
            year=self.today.year,
        )
        balance.allocated_days = 400
        balance.save(update_fields=["allocated_days"])

    def _payload(self, from_date, to_date):
        return {
            "leave_type": "casual",
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "reason": "UAT date validation",
        }

    def test_accepts_the_configured_date_window(self):
        from_date = self.today - timedelta(days=30)
        to_date = self.today + timedelta(days=10)
        response = self.client.post(self.url, self._payload(from_date, to_date), format="json")

        self.assertEqual(response.status_code, 201, response.data)

    def test_rejects_dates_outside_the_window(self):
        too_old = self.client.post(
            self.url,
            self._payload(self.today - timedelta(days=31), self.today),
            format="json",
        )
        self.assertEqual(too_old.status_code, 400, too_old.data)
        self.assertIn("from_date", too_old.data)

        too_far = self.client.post(
            self.url,
            self._payload(self.today, self.today + timedelta(days=366)),
            format="json",
        )
        self.assertEqual(too_far.status_code, 400, too_far.data)
        self.assertIn("to_date", too_far.data)

    def test_rejects_reversed_and_cross_year_ranges(self):
        reversed_range = self.client.post(
            self.url,
            self._payload(self.today + timedelta(days=2), self.today + timedelta(days=1)),
            format="json",
        )
        self.assertEqual(reversed_range.status_code, 400, reversed_range.data)
        self.assertIn("to_date", reversed_range.data)

        cross_year = self.client.post(
            self.url,
            self._payload(self.today.replace(month=12, day=31), self.today.replace(month=12, day=31) + timedelta(days=1)),
            format="json",
        )
        self.assertEqual(cross_year.status_code, 400, cross_year.data)
        self.assertIn("date_range", cross_year.data)
