from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership

from .models import Block, Plot, PlotBooking, PlotStatusHistory, Project


class PlotBookingApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="manager", password="password123")
        self.viewer = user_model.objects.create_user(username="viewer", password="password123")
        self.other_user = user_model.objects.create_user(username="other", password="password123")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=self.other_organization, user=self.other_user, role=OrganizationMembership.Role.MANAGER)
        self.project = Project.objects.create(organization=self.organization, name="Green", code="G")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A", code="A")
        self.other_project = Project.objects.create(organization=self.other_organization, name="Other", code="O")
        self.other_block = Block.objects.create(organization=self.other_organization, project=self.other_project, name="B", code="B")
        self.lead = Lead.objects.create(organization=self.organization, first_name="Ada", last_name="Lovelace", phone="111")
        self.other_lead = Lead.objects.create(organization=self.other_organization, first_name="Grace", phone="222")
        self.visit = Sitevisit.objects.create(organization=self.organization, lead=self.lead, site="Green")
        self.other_visit = Sitevisit.objects.create(organization=self.organization, lead=Lead.objects.create(organization=self.organization, first_name="Other", phone="333"))
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def plot(self, number="A-101", status=Plot.Status.AVAILABLE, organization=None):
        organization = organization or self.organization
        return Plot.objects.create(
            organization=organization,
            project=self.project if organization == self.organization else self.other_project,
            block=self.block if organization == self.organization else self.other_block,
            plot_number=number, size=Decimal("100.00"), status=status,
        )

    def booking_url(self):
        return reverse("inventory:bookings", args=[self.organization.slug])

    def create_booking(self, plot, **extra):
        payload = {"lead_id": self.lead.id, "plot_id": plot.id, "site_visit_id": self.visit.id, "notes": "Interested"}
        payload.update(extra)
        return self.client.post(self.booking_url(), payload, format="json")

    def test_create_booking_selects_plot_and_writes_history(self):
        plot = self.plot()
        response = self.create_booking(plot)
        self.assertEqual(response.status_code, 201, response.data)
        booking = PlotBooking.objects.get()
        self.assertEqual(booking.status, PlotBooking.Status.PENDING)
        plot.refresh_from_db()
        self.assertEqual(plot.status, Plot.Status.HOLD)
        self.assertTrue(PlotStatusHistory.objects.filter(plot=plot, old_status="available", new_status="hold").exists())

    def test_select_endpoint_and_relationship_validation(self):
        plot = self.plot()
        url = reverse("inventory:plot-select", args=[self.organization.slug, plot.id])
        response = self.client.post(url, {"lead_id": self.lead.id, "site_visit_id": self.visit.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        plot = self.plot("A-102")
        response = self.create_booking(plot, site_visit_id=self.other_visit.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("site_visit_id", response.data)

    def test_cross_organization_and_unavailable_plots_are_rejected(self):
        own_plot = self.plot()
        self.assertEqual(self.create_booking(own_plot, lead_id=self.other_lead.id).status_code, 404)
        foreign_plot = self.plot("O-1", organization=self.other_organization)
        self.assertEqual(self.create_booking(foreign_plot).status_code, 404)
        unavailable = self.plot("A-102", status=Plot.Status.BLOCKED)
        self.assertEqual(self.create_booking(unavailable).status_code, 400)

    def test_only_one_active_booking_and_cancelled_booking_can_be_replaced(self):
        plot = self.plot()
        response = self.create_booking(plot)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.create_booking(plot).status_code, 400)
        booking = PlotBooking.objects.get(plot=plot)
        cancel = reverse("inventory:booking-cancel", args=[self.organization.slug, booking.id])
        self.assertEqual(self.client.post(cancel, {"reason": "Changed mind"}, format="json").status_code, 200)
        plot.refresh_from_db()
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)
        self.assertEqual(self.create_booking(plot).status_code, 201)

    def test_confirm_and_confirmed_cancellation_use_inventory_transitions(self):
        plot = self.plot()
        self.create_booking(plot)
        booking = PlotBooking.objects.get(plot=plot)
        confirm = reverse("inventory:booking-confirm", args=[self.organization.slug, booking.id])
        self.assertEqual(self.client.post(confirm, {}, format="json").status_code, 200)
        plot.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual((booking.status, plot.status), (PlotBooking.Status.CONFIRMED, Plot.Status.BOOKED))
        cancel = reverse("inventory:booking-cancel", args=[self.organization.slug, booking.id])
        self.assertEqual(self.client.post(cancel, {"reason": "Financing failed"}, format="json").status_code, 200)
        plot.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual((booking.status, plot.status), (PlotBooking.Status.CANCELLED, Plot.Status.AVAILABLE))
        self.assertEqual(PlotStatusHistory.objects.filter(plot=plot).count(), 4)
        self.assertEqual(self.client.post(confirm, {}, format="json").status_code, 400)

    def test_lists_isolation_and_read_only_permission(self):
        plot = self.plot()
        self.create_booking(plot)
        booking = PlotBooking.objects.get()
        self.assertEqual(self.client.get(reverse("inventory:lead-bookings", args=[self.organization.slug, self.lead.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("inventory:plot-bookings", args=[self.organization.slug, plot.id])).status_code, 200)
        viewer = APIClient(); viewer.force_authenticate(self.viewer)
        self.assertEqual(viewer.get(self.booking_url()).status_code, 200)
        self.assertEqual(viewer.post(reverse("inventory:booking-confirm", args=[self.organization.slug, booking.id]), {}, format="json").status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:booking-detail", args=[self.organization.slug, booking.id + 999])).status_code, 404)
