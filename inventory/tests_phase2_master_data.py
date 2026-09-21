from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from inventory.models import Block, Plot, PlotStatusHistory
from organizations.models import Organization, OrganizationMembership, Project
from system_settings.models import MasterData


class Phase2PlotStatusMasterDataTests(APITestCase):
    """FR-P2-01/03, FR-P8-02, GNFR-09: plot statuses bind to project master data."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="plot-status-manager",
            password="Password@123",
        )
        self.organization = Organization.objects.create(name="Plot Status Org", slug="plot-status-org")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            name="Plot Status Project",
            code="PLOT-STATUS",
        )
        self.other_project = Project.objects.create(
            organization=self.organization,
            name="Other Plot Project",
            code="OTHER-PLOT",
        )
        self.block = Block.all_objects.create(
            organization=self.organization,
            project=self.project,
            name="A Block",
            code="A",
        )
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)

    def create_plot(self, number="A-101", status=Plot.Status.AVAILABLE):
        return Plot.all_objects.create(
            organization=self.organization,
            project=self.project,
            block=self.block,
            plot_number=number,
            size=Decimal("100.00"),
            status=status,
        )

    def status_url(self, plot):
        return (
            f"/api/v1/organizations/{self.organization.slug}/"
            f"inventory/plots/{plot.id}/status/"
        )

    def test_confirmed_statuses_are_seeded_as_protected_items_and_used(self):
        plot = self.create_plot()

        response = self.client.post(
            self.status_url(plot),
            {"status": "under_construction", "reason": "Development started"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        statuses = MasterData.all_objects.filter(
            organization=self.organization,
            project=self.project,
            master_type="plot_status",
        )
        self.assertEqual(
            set(statuses.values_list("code", flat=True)),
            {
                "available",
                "blocked",
                "hold",
                "booked",
                "sold",
                "cancelled",
                "under_construction",
            },
        )
        self.assertFalse(statuses.filter(is_system=False).exists())
        self.assertFalse(Plot._meta.get_field("status").choices)
        self.assertFalse(PlotStatusHistory._meta.get_field("old_status").choices)
        self.assertFalse(PlotStatusHistory._meta.get_field("new_status").choices)

    def test_deactivated_status_is_rejected_without_plot_or_history_mutation(self):
        seed_plot = self.create_plot(number="A-seed")
        self.client.post(
            self.status_url(seed_plot),
            {"status": "under_construction", "reason": "Seed catalogue"},
            format="json",
        )
        blocked = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="plot_status",
            code="blocked",
        )
        blocked.is_active = False
        blocked.save(update_fields=["is_active"])
        plot = self.create_plot(number="A-inactive")

        response = self.client.post(
            self.status_url(plot),
            {"status": "blocked", "reason": "Customer request"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)
        plot.refresh_from_db()
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)
        self.assertFalse(PlotStatusHistory.objects.filter(plot=plot).exists())

    def test_status_filter_rejects_inactive_current_project_status(self):
        plot = self.create_plot()
        self.client.post(
            self.status_url(plot),
            {"status": "under_construction", "reason": "Seed catalogue"},
            format="json",
        )
        available = MasterData.all_objects.get(
            organization=self.organization,
            project=self.project,
            master_type="plot_status",
            code="available",
        )
        available.is_active = False
        available.save(update_fields=["is_active"])

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/inventory/plots/",
            {"status": "available"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)

    def test_other_project_status_cannot_authorize_current_project_transition(self):
        MasterData.all_objects.create(
            organization=self.organization,
            project=self.other_project,
            master_type="plot_status",
            code="custom_other_project",
            name="Custom Other Project",
        )
        plot = self.create_plot()

        response = self.client.post(
            self.status_url(plot),
            {"status": "custom_other_project", "reason": "Wrong scope"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)
