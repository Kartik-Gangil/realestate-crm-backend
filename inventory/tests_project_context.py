from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Block, Payment, Plot, PlotBooking, Project, Registry
from leads.models import Lead
from organizations.models import Organization, OrganizationMembership


class ProjectContextApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="project-admin@example.com",
            email="project-admin@example.com",
            password="Valid123!",
            is_superuser=True,
        )
        self.organization = Organization.objects.create(name="Scoped Org", slug="scoped-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.project_a = Project.objects.create(organization=self.organization, name="Project A", code="A")
        self.project_b = Project.objects.create(organization=self.organization, name="Project B", code="B")
        self.block_a = Block.objects.create(organization=self.organization, project=self.project_a, name="Block A", code="A")
        self.block_b = Block.objects.create(organization=self.organization, project=self.project_b, name="Block B", code="B")
        self.plot_a = Plot.objects.create(
            organization=self.organization, project=self.project_a, block=self.block_a,
            plot_number="A-001", size="100", rate_per_sq_unit="10", total_price="1000",
        )
        self.plot_b = Plot.objects.create(
            organization=self.organization, project=self.project_b, block=self.block_b,
            plot_number="B-001", size="100", rate_per_sq_unit="10", total_price="1000",
        )
        self.lead_a = Lead.objects.create(
            organization=self.organization, project=self.project_a,
            first_name="Project", last_name="A", phone="9000000001", email="a@example.com",
        )
        self.lead_b = Lead.objects.create(
            organization=self.organization, project=self.project_b,
            first_name="Project", last_name="B", phone="9000000002", email="b@example.com",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        booking_a = PlotBooking.objects.create(
            organization=self.organization,
            lead=self.lead_a,
            plot=self.plot_a,
            status=PlotBooking.Status.CONFIRMED,
            final_price="1000.00",
        )
        booking_b = PlotBooking.objects.create(
            organization=self.organization,
            lead=self.lead_b,
            plot=self.plot_b,
            status=PlotBooking.Status.CONFIRMED,
            final_price="2000.00",
        )
        self.booking_a = booking_a
        self.booking_b = booking_b
        self.registry_a = Registry.objects.create(
            organization=self.organization,
            booking=booking_a,
            registry_number="REG-A",
        )
        self.registry_b = Registry.objects.create(
            organization=self.organization,
            booking=booking_b,
            registry_number="REG-B",
        )
        self.payment_a = Payment.objects.create(
            organization=self.organization,
            booking=booking_a,
            payment_id="PAY-A",
            amount="100.00",
            payment_method="cash",
            status=Payment.Status.SUCCESS,
            payment_date="2026-10-15",
        )
        self.payment_b = Payment.objects.create(
            organization=self.organization,
            booking=booking_b,
            payment_id="PAY-B",
            amount="200.00",
            payment_method="upi",
            status=Payment.Status.SUCCESS,
            payment_date="2026-10-15",
        )

    def test_plot_list_requires_project_header_and_returns_only_active_project(self):
        url = "/api/organizations/scoped-org/inventory/plots/"

        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 400)

        response = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.plot_a.id])

    def test_plot_create_assigns_active_project_and_returns_created_plot(self):
        """FR-P8-01/API-P8-03: plot creation is scoped to X-Project-ID."""
        url = "/api/organizations/scoped-org/inventory/plots/"
        response = self.client.post(
            url,
            {
                "block": self.block_a.id,
                "plot_number": "A-002",
                "size": "120.00",
                "plot_type": "residential",
                "rate_per_sq_unit": "10.00",
                "total_price": "1200.00",
                "facing": "East",
                "dimensions": "10 x 12",
                "description": "Project-scoped test plot",
            },
            format="json",
            HTTP_X_PROJECT_ID=str(self.project_a.id),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["project"]["id"], self.project_a.id)
        self.assertEqual(
            Plot.objects.get(organization=self.organization, plot_number="A-002").project_id,
            self.project_a.id,
        )

    def test_lead_list_requires_project_header_and_returns_only_active_project(self):
        url = "/api/organizations/scoped-org/leads/"

        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 400)

        response = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_b.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.lead_b.id])

    def test_payment_list_requires_project_header_and_returns_only_active_project(self):
        url = "/api/organizations/scoped-org/payments/"

        missing = self.client.get(url)
        self.assertEqual(missing.status_code, 400)

        response_a = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual([item["payment_id"] for item in response_a.data["results"]], ["PAY-A"])

        response_b = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_b.id))
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual([item["payment_id"] for item in response_b.data["results"]], ["PAY-B"])

    def test_booking_list_is_scoped_to_active_project(self):
        url = "/api/organizations/scoped-org/inventory/bookings/"

        response_a = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual([item["id"] for item in response_a.data["results"]], [self.booking_a.id])

        response_b = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_b.id))
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual([item["id"] for item in response_b.data["results"]], [self.booking_b.id])

    def test_registry_list_is_scoped_to_active_project(self):
        url = "/api/organizations/scoped-org/registries/"

        response_a = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_a.id))
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual([item["id"] for item in response_a.data["results"]], [self.registry_a.id])

        response_b = self.client.get(url, HTTP_X_PROJECT_ID=str(self.project_b.id))
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual([item["id"] for item in response_b.data["results"]], [self.registry_b.id])
