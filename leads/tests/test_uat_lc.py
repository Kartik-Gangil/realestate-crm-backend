"""Attached UAT report regressions for LC-01."""

from django.test import TestCase
from rest_framework.test import APIClient

from core.tests.factories import make_lead, make_member, make_organization, make_project


class UatLcLeadDeletionTests(TestCase):
    """FR-P5-08/GNFR-05 [LC-01]: individual deletion needs delete permission."""

    def setUp(self):
        self.organization = make_organization("uat-lc-01")
        self.project = make_project(self.organization, "LC01")
        self.manager = make_member(self.organization, role="manager", projects=[self.project])
        self.admin = make_member(self.organization, role="admin", projects=[self.project])
        self.lead = make_lead(self.organization, self.project, first_name="Delete Me")
        self.headers = {"HTTP_X_PROJECT_ID": str(self.project.pk)}

    def test_manager_cannot_delete_one_lead_with_edit_permission_only(self):
        client = APIClient()
        client.force_authenticate(self.manager.user)

        response = client.delete(
            f"/api/v1/organizations/{self.organization.slug}/leads/{self.lead.pk}/",
            **self.headers,
        )

        self.assertEqual(response.status_code, 403, response.data)

    def test_admin_can_still_delete_one_lead(self):
        client = APIClient()
        client.force_authenticate(self.admin.user)

        response = client.delete(
            f"/api/v1/organizations/{self.organization.slug}/leads/{self.lead.pk}/",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200, response.data)
