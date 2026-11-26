from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from documents.models import CustomerDocument, DocumentCategory
from leads.models import Lead, Sitevisit

from .models import Block, Plot, PlotBooking, PlotStatusHistory


class PlotBookingApiTests(TestCase):
    def setUp(self):
        self.organization = make_organization("acme")
        self.other_organization = make_organization("other")
        self.project = make_project(self.organization, "G")
        self.block = Block.objects.create(organization=self.organization, project=self.project, name="A", code="A")
        self.other_project = make_project(self.other_organization, "O")
        self.other_block = Block.objects.create(organization=self.other_organization, project=self.other_project, name="B", code="B")
        self.manager_membership = make_member(self.organization, role="manager", projects=[self.project])
        self.viewer_membership = make_member(self.organization, role="telecaller", projects=[self.project])
        self.other_membership = make_member(self.other_organization, role="manager", projects=[self.other_project])
        self.manager = self.manager_membership.user
        self.viewer = self.viewer_membership.user
        self.other_user = self.other_membership.user
        self.lead = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Ada",
            last_name="Lovelace",
            phone="9000000103",
            lifecycle_status="site_visit_completed",
        )
        self.other_lead = Lead.objects.create(organization=self.other_organization, project=self.other_project, first_name="Grace", phone="9000000104")
        self.visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=self.lead,
            site="Green",
            status=Sitevisit.Status.COMPLETED,
        )
        self.other_visit = Sitevisit.objects.create(
            organization=self.organization,
            project=self.project,
            lead=Lead.objects.create(organization=self.organization, project=self.project, first_name="Other", phone="9000000105"),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def headers(self, project=None):
        return project_request_kwargs(project or self.project)

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
        key = payload.pop("idempotency_key", f"phase4-{plot.id}-{PlotBooking.objects.count()}")
        return self.client.post(self.booking_url(), payload, format="json", HTTP_X_IDEMPOTENCY_KEY=key, **self.headers())

    def test_create_booking_selects_plot_and_writes_history(self):
        plot = self.plot()
        response = self.create_booking(plot)
        self.assertEqual(response.status_code, 201, response.data)
        booking = PlotBooking.objects.get()
        self.assertEqual(booking.status, PlotBooking.Status.PENDING)
        plot.refresh_from_db()
        self.assertEqual(plot.status, Plot.Status.BOOKED)
        self.assertTrue(PlotStatusHistory.objects.filter(plot=plot, old_status="available", new_status="booked").exists())

    def test_select_endpoint_and_relationship_validation(self):
        plot = self.plot()
        url = reverse("inventory:plot-select", args=[self.organization.slug, plot.id])
        response = self.client.post(url, {"lead_id": self.lead.id, "site_visit_id": self.visit.id}, format="json", HTTP_X_IDEMPOTENCY_KEY="plot-select-1", **self.headers())
        self.assertEqual(response.status_code, 201, response.data)
        plot = self.plot("A-102")
        response = self.create_booking(plot, site_visit_id=self.other_visit.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("site_visit", response.data)

    def test_cross_organization_and_unavailable_plots_are_rejected(self):
        own_plot = self.plot()
        self.assertEqual(self.create_booking(own_plot, lead_id=self.other_lead.id).status_code, 404)
        foreign_plot = self.plot("O-1", organization=self.other_organization)
        self.assertEqual(self.create_booking(foreign_plot).status_code, 404)
        unavailable = self.plot("A-102", status=Plot.Status.BLOCKED)
        self.assertEqual(self.create_booking(unavailable).status_code, 409)

    def test_only_one_active_booking_and_cancelled_booking_can_be_replaced(self):
        plot = self.plot()
        response = self.create_booking(plot)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.create_booking(plot).status_code, 409)
        booking = PlotBooking.objects.get(plot=plot)
        cancel = reverse("inventory:booking-cancel", args=[self.organization.slug, booking.id])
        cancel_response = self.client.post(cancel, {"reason": "Changed mind"}, format="json", **self.headers())
        self.assertEqual(cancel_response.status_code, 200, cancel_response.data)
        plot.refresh_from_db()
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)
        self.assertEqual(self.create_booking(plot).status_code, 201)

    def test_confirm_and_confirmed_cancellation_use_inventory_transitions(self):
        plot = self.plot()
        self.create_booking(plot)
        booking = PlotBooking.objects.get(plot=plot)
        category = DocumentCategory.objects.create(
            organization=self.organization, name="Identity", code="identity"
        )
        CustomerDocument.objects.create(
            organization=self.organization,
            customer=booking.customer,
            document_category=category,
            document_name="Identity",
            file=SimpleUploadedFile("identity.pdf", b"verified identity", content_type="application/pdf"),
            file_name="identity.pdf",
            file_size=len(b"verified identity"),
            content_type="application/pdf",
            version=1,
            status=CustomerDocument.Status.VERIFIED,
            verified_by=self.manager,
        )
        confirm = reverse("inventory:booking-confirm", args=[self.organization.slug, booking.id])
        self.assertEqual(self.client.post(confirm, {}, format="json", **self.headers()).status_code, 200)
        plot.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual((booking.status, plot.status), (PlotBooking.Status.CONFIRMED, Plot.Status.BOOKED))
        cancel = reverse("inventory:booking-cancel", args=[self.organization.slug, booking.id])
        self.assertEqual(self.client.post(cancel, {"reason": "Financing failed"}, format="json", **self.headers()).status_code, 200)
        plot.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual((booking.status, plot.status), (PlotBooking.Status.CANCELLED, Plot.Status.AVAILABLE))
        self.assertEqual(PlotStatusHistory.objects.filter(plot=plot).count(), 3)
        self.assertEqual(self.client.post(confirm, {}, format="json", **self.headers()).status_code, 400)

    def test_lists_isolation_and_read_only_permission(self):
        plot = self.plot()
        self.create_booking(plot)
        booking = PlotBooking.objects.get()
        self.assertEqual(self.client.get(reverse("inventory:lead-bookings", args=[self.organization.slug, self.lead.id]), **self.headers()).status_code, 200)
        self.assertEqual(self.client.get(reverse("inventory:plot-bookings", args=[self.organization.slug, plot.id]), **self.headers()).status_code, 200)
        viewer = APIClient(); viewer.force_authenticate(self.viewer)
        self.assertEqual(viewer.get(self.booking_url(), **self.headers()).status_code, 200)
        self.assertEqual(viewer.post(reverse("inventory:booking-confirm", args=[self.organization.slug, booking.id]), {}, format="json", **self.headers()).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:booking-detail", args=[self.organization.slug, booking.id + 999]), **self.headers()).status_code, 404)
