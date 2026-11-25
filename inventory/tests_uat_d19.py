"""FR-P10-02 / FR-P10-05 [UAT-D19] customer edit and archive acceptance tests."""

from rest_framework.test import APIClient
from django.test import TestCase

from core.tests.factories import make_lead, make_member, make_organization, make_project

from .customer_services import create_customer
from .models import Customer


class UatD19CustomerEditArchiveTests(TestCase):
    def setUp(self):
        self.organization = make_organization("uat-d19-customer")
        self.project = make_project(self.organization, "D19")
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.admin_membership = make_member(self.organization, role="admin", projects=[self.project])
        self.telecaller_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.lead = make_lead(
            self.organization,
            self.project,
            first_name="UAT",
            phone="9000001901",
            email="uat-d19@example.com",
            lifecycle_status="site_visit_completed",
            assigned_membership=self.telecaller_membership,
        )
        self.customer = create_customer(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            full_name="UAT Customer",
            phone="9000001901",
            email="uat-d19@example.com",
            address="Address",
            actor=self.manager_membership.user,
        )
        self.url = f"/api/v1/organizations/{self.organization.slug}/customers/{self.customer.pk}/"
        self.headers = {"HTTP_X_PROJECT_ID": str(self.project.pk)}

    def test_manager_and_admin_can_edit_customer(self):
        for user, name in ((self.manager_membership.user, "Manager Edit"), (self.admin_membership.user, "Admin Edit")):
            client = APIClient()
            client.force_authenticate(user)
            response = client.patch(self.url, {"full_name": name}, format="json", **self.headers)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["full_name"], name)

    def test_archive_is_inactive_with_required_reason_and_delete_is_not_available(self):
        client = APIClient()
        client.force_authenticate(self.manager_membership.user)

        missing_reason = client.patch(self.url, {"status": Customer.Status.INACTIVE}, format="json", **self.headers)
        self.assertEqual(missing_reason.status_code, 400, missing_reason.data)
        self.assertIn("reason", missing_reason.data)

        archived = client.patch(
            self.url,
            {"status": Customer.Status.INACTIVE, "reason": "Customer requested archive"},
            format="json",
            **self.headers,
        )
        self.assertEqual(archived.status_code, 200, archived.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.status, Customer.Status.INACTIVE)
        self.assertEqual(self.customer.lifecycle_reason, "Customer requested archive")

        self.assertEqual(client.delete(self.url, **self.headers).status_code, 405)

    def test_telecaller_cannot_edit_or_archive_customer(self):
        client = APIClient()
        client.force_authenticate(self.telecaller_membership.user)
        response = client.patch(self.url, {"full_name": "Not allowed"}, format="json", **self.headers)
        self.assertEqual(response.status_code, 403)
