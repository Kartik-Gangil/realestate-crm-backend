from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Organization, OrganizationMembership
from .services import ensure_default_roles


class UatLcEmployeeRbacTests(APITestCase):
    """FR-P3-01/FR-P3-03/DM-P3-02 [LC-07]."""

    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="HR Org", slug="hr-org")
        self.roles = ensure_default_roles(self.organization)
        self.hr_admin = user_model.objects.create_user(
            username="hr-admin@uat.example",
            email="hr-admin@uat.example",
            password="Valid123!",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.hr_admin,
            role="hr-admin",
            organization_role=self.roles["hr-admin"],
        )
        self.client.force_authenticate(self.hr_admin)

    def test_hr_admin_can_create_employee_with_role_assignment_lc07(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/users/",
            {
                "email": "new-employee@uat.example",
                "temporary_password": "Valid123!",
                "first_name": "New",
                "last_name": "Employee",
                "role": "telecaller",
                "role_id": self.roles["telecaller"].id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        created = OrganizationMembership.objects.get(
            organization=self.organization,
            user__email="new-employee@uat.example",
        )
        self.assertEqual(created.organization_role_id, self.roles["telecaller"].id)

