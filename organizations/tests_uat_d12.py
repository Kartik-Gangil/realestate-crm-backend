"""FR-P15-01 / DM-P15-01 [UAT-D12] employee mobile acceptance tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Organization, OrganizationMembership


class UatD12EmployeeMobileTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="UAT-D12 org", slug="uat-d12-org")
        self.admin = get_user_model().objects.create_user(
            username="admin@uat-d12.test",
            email="admin@uat-d12.test",
            password="Admin123!",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role="admin",
            employee_id="EMP0001",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _url(self):
        return f"/api/v1/organizations/{self.organization.slug}/employees/"

    def _payload(self, email, mobile_number="9876543210"):
        return {
            "email": email,
            "temporary_password": "Temporary123!",
            "first_name": "UAT",
            "last_name": "Employee",
            "role": "telecaller",
            "mobile_number": mobile_number,
        }

    def test_create_normalizes_indian_mobile_and_allows_blank(self):
        response = self.client.post(
            self._url(),
            self._payload("first@uat-d12.test", "098765-43210"),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        employee = OrganizationMembership.objects.get(user__email="first@uat-d12.test")
        self.assertEqual(employee.mobile_number, "+919876543210")
        self.assertEqual(response.data["mobile_number"], "+919876543210")

        blank_response = self.client.post(
            self._url(),
            self._payload("blank@uat-d12.test", ""),
            format="json",
        )

        self.assertEqual(blank_response.status_code, 201, blank_response.data)
        blank_employee = OrganizationMembership.objects.get(user__email="blank@uat-d12.test")
        self.assertEqual(blank_employee.mobile_number, "")

    def test_duplicate_normalized_mobile_is_rejected_with_a_field_error(self):
        first_response = self.client.post(
            self._url(),
            self._payload("first@uat-d12.test", "+91 98765-43210"),
            format="json",
        )
        self.assertEqual(first_response.status_code, 201, first_response.data)

        duplicate_response = self.client.post(
            self._url(),
            self._payload("duplicate@uat-d12.test", "9876543210"),
            format="json",
        )

        self.assertEqual(duplicate_response.status_code, 400, duplicate_response.data)
        self.assertIn("mobile_number", duplicate_response.data)

    def test_update_normalizes_mobile_and_rejects_an_existing_number(self):
        first_response = self.client.post(
            self._url(),
            self._payload("first@uat-d12.test", "9876543210"),
            format="json",
        )
        second_response = self.client.post(
            self._url(),
            self._payload("second@uat-d12.test", "9123456789"),
            format="json",
        )
        self.assertEqual(first_response.status_code, 201, first_response.data)
        self.assertEqual(second_response.status_code, 201, second_response.data)
        second = OrganizationMembership.objects.get(user__email="second@uat-d12.test")

        update_response = self.client.patch(
            f"{self._url()}{second.pk}/",
            {"mobile_number": "09876543219"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200, update_response.data)
        second.refresh_from_db()
        self.assertEqual(second.mobile_number, "+919876543219")

        duplicate_update = self.client.patch(
            f"{self._url()}{second.pk}/",
            {"mobile_number": "+91 98765-43210"},
            format="json",
        )
        self.assertEqual(duplicate_update.status_code, 400, duplicate_update.data)
        self.assertIn("mobile_number", duplicate_update.data)
