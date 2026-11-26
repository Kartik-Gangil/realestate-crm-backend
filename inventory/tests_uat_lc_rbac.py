from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from organizations.models import Organization, OrganizationMembership, ProjectAssignment
from organizations.services import ensure_default_roles

from .models import Block, Project


class UatLcRbacTests(APITestCase):
    """FR-P3-03/FR-P8-07/FR-P10-06/GNFR-05 [LC-02, LC-03]."""

    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="UAT Org", slug="uat-org")
        self.roles = ensure_default_roles(self.organization)
        self.project = Project.objects.create(organization=self.organization, name="UAT Project", code="UAT")
        self.block = Block.objects.create(
            organization=self.organization,
            project=self.project,
            name="Block A",
            code="A",
        )

        self.admin = user_model.objects.create_user(
            username="admin@uat.example",
            email="admin@uat.example",
            password="Valid123!",
        )
        self.telecaller = user_model.objects.create_user(
            username="telecaller@uat.example",
            email="telecaller@uat.example",
            password="Valid123!",
        )
        self.accounts = user_model.objects.create_user(
            username="accounts@uat.example",
            email="accounts@uat.example",
            password="Valid123!",
        )
        self.sve = user_model.objects.create_user(
            username="sve@uat.example",
            email="sve@uat.example",
            password="Valid123!",
        )

        self.memberships = {}
        for key, user, role_code in (
            ("admin", self.admin, "admin"),
            ("telecaller", self.telecaller, "telecaller"),
            ("accounts", self.accounts, "accounts"),
            ("sve", self.sve, "site-visit-executive"),
        ):
            membership = OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role_code if role_code != "site-visit-executive" else "site-visit-executive",
                organization_role=self.roles[role_code],
            )
            ProjectAssignment.objects.create(
                membership=membership,
                project=self.project,
                role=self.roles[role_code],
                assigned_by=self.admin,
            )
            self.memberships[key] = membership

    def headers(self):
        return {"HTTP_X_PROJECT_ID": str(self.project.id)}

    def plot_payload(self, plot_number="A-1"):
        return {
            "block": self.block.id,
            "plot_number": plot_number,
            "size": "100",
            "rate_per_sq_unit": "1000",
            "total_price": "100000",
        }

    def test_accounts_and_telecaller_cannot_create_plots_without_plots_add_lc02(self):
        for user, number in ((self.accounts, "A-ACCOUNTS"), (self.telecaller, "A-TELECALLER")):
            self.client.force_authenticate(user)
            response = self.client.post(
                f"/api/organizations/{self.organization.slug}/inventory/plots/",
                self.plot_payload(number),
                format="json",
                **self.headers(),
            )
            self.assertEqual(response.status_code, 403, response.data)

    def test_site_visit_executive_cannot_create_customers_without_customers_add_lc03(self):
        self.client.force_authenticate(self.sve)
        response = self.client.post(
            f"/api/organizations/{self.organization.slug}/customers/",
            {
                "full_name": "Unauthorized Customer",
                "phone": "+919876543210",
                "email": "unauthorized@example.com",
            },
            format="json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_empty_customer_payload_returns_validation_not_duplicate_lc17(self):
        from .customer_services import create_customer

        create_customer(
            organization=self.organization,
            project=self.project,
            full_name="Existing Customer",
            phone="9000000999",
            email="existing@example.com",
            actor=self.admin,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/organizations/{self.organization.slug}/customers/",
            {},
            format="json",
            **self.headers(),
        )

        self.assertEqual(response.status_code, 400, response.data)

