from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership

from .models import Block, Plot, PlotSelection


class PlotSelectionApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model(); self.manager = user_model.objects.create_user(username="manager", password="x"); self.viewer = user_model.objects.create_user(username="viewer", password="x")
        self.org = Organization.objects.create(name="Acme", slug="acme"); self.other = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(organization=self.org, user=self.manager, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role=OrganizationMembership.Role.TELECALLER)
        self.block = Block.objects.create(organization=self.org, name="A", code="A")
        self.plot = Plot.objects.create(organization=self.org, block=self.block, plot_number="A-101", size=Decimal("100"), facing="North")
        self.lead = Lead.objects.create(organization=self.org, first_name="Ada", phone="1"); self.visit = Sitevisit.objects.create(organization=self.org, lead=self.lead)
        self.client = APIClient(); self.client.force_authenticate(self.manager)

    def select_url(self, plot=None): return reverse("inventory:plot-inventory-select", args=[self.org.slug, (plot or self.plot).id])

    def test_inventory_list_detail_search_filters_and_availability(self):
        response = self.client.get(reverse("inventory:plot-inventory", args=[self.org.slug]), {"search": "A-101", "facing": "North", "available": "true", "page_size": 1})
        self.assertEqual(response.status_code, 200); self.assertEqual(response.data["count"], 1); self.assertTrue(response.data["results"][0]["available"])
        detail = self.client.get(reverse("inventory:plot-inventory-detail", args=[self.org.slug, self.plot.id]))
        self.assertEqual(detail.status_code, 200); self.assertTrue(detail.data["available"])
        availability = self.client.get(reverse("inventory:plot-inventory-availability", args=[self.org.slug, self.plot.id]))
        self.assertTrue(availability.data["available"])

    def test_selection_conflict_release_expiry_and_idempotent_confirmation(self):
        payload = {"lead_id": self.lead.id, "site_visit_id": self.visit.id}
        response = self.client.post(self.select_url(), payload, format="json"); self.assertEqual(response.status_code, 201, response.data)
        selection = PlotSelection.objects.get(); self.assertEqual(selection.status, PlotSelection.Status.ACTIVE)
        duplicate = self.client.post(self.select_url(), payload, format="json"); self.assertEqual(duplicate.status_code, 409); self.assertEqual(duplicate.data["code"], "PLOT_ALREADY_SELECTED")
        confirm_url = reverse("inventory:plot-selection-confirm", args=[self.org.slug, selection.id])
        self.assertEqual(self.client.post(confirm_url, {}, format="json").status_code, 200)
        self.assertEqual(self.client.post(confirm_url, {}, format="json").status_code, 200)
        self.plot.refresh_from_db(); self.assertEqual(self.plot.status, Plot.Status.AVAILABLE)
        second = Plot.objects.create(organization=self.org, block=self.block, plot_number="A-102", size=Decimal("100"))
        active = self.client.post(self.select_url(second), payload, format="json"); self.assertEqual(active.status_code, 201)
        active_selection = PlotSelection.objects.get(plot=second); release = reverse("inventory:plot-selection-release", args=[self.org.slug, active_selection.id])
        self.assertEqual(self.client.post(release, {"reason": "Alternative"}, format="json").status_code, 200)
        self.assertEqual(self.client.post(reverse("inventory:plot-selection-confirm", args=[self.org.slug, active_selection.id]), {}, format="json").status_code, 409)
        expired = Plot.objects.create(organization=self.org, block=self.block, plot_number="A-103", size=Decimal("100"))
        old = PlotSelection.objects.create(organization=self.org, plot=expired, selected_by=self.manager, expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(self.select_url(expired), payload, format="json").status_code, 201); old.refresh_from_db(); self.assertEqual(old.status, PlotSelection.Status.EXPIRED)

    def test_unavailable_permissions_and_invalid_relationships(self):
        self.plot.status = Plot.Status.BOOKED; self.plot.save()
        response = self.client.post(self.select_url(), {"lead_id": self.lead.id}, format="json"); self.assertEqual(response.status_code, 409); self.assertEqual(response.data["code"], "PLOT_UNAVAILABLE")
        self.plot.status = Plot.Status.AVAILABLE; self.plot.save()
        foreign_lead = Lead.objects.create(organization=self.other, first_name="Foreign", phone="2")
        self.assertEqual(self.client.post(self.select_url(), {"lead_id": foreign_lead.id}, format="json").status_code, 404)
        other_lead = Lead.objects.create(organization=self.org, first_name="Other", phone="3"); wrong_visit = Sitevisit.objects.create(organization=self.org, lead=other_lead)
        self.assertEqual(self.client.post(self.select_url(), {"lead_id": self.lead.id, "site_visit_id": wrong_visit.id}, format="json").status_code, 400)
        viewer = APIClient(); viewer.force_authenticate(self.viewer)
        self.assertEqual(viewer.get(reverse("inventory:plot-inventory", args=[self.org.slug])).status_code, 200)
        self.assertEqual(viewer.post(self.select_url(), {"lead_id": self.lead.id}, format="json").status_code, 403)
