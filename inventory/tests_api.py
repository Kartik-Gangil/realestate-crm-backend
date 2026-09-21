from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership

from .models import Block, Plot


class PlotApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="acme@example.com", email="acme@example.com", password="password123")
        self.other_user = user_model.objects.create_user(username="other@example.com", email="other@example.com", password="password123")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role=OrganizationMembership.Role.ADMIN)
        OrganizationMembership.objects.create(organization=self.other_organization, user=self.other_user, role=OrganizationMembership.Role.ADMIN)
        self.block = Block.objects.create(organization=self.organization, name="A Block", code="A")
        self.other_block = Block.objects.create(organization=self.organization, name="B Block", code="B")
        self.foreign_block = Block.objects.create(organization=self.other_organization, name="Foreign Block", code="F")
        self.plot = self.make_plot("A-101")
        self.foreign_plot = Plot.objects.create(
            organization=self.other_organization, block=self.foreign_block,
            plot_number="F-101", size=Decimal("100"),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def list_url(self):
        return reverse("inventory:plots", args=[self.organization.slug])

    def detail_url(self, plot):
        return reverse("inventory:plot-detail", args=[self.organization.slug, plot.id])

    def make_plot(self, number, **overrides):
        values = {
            "organization": self.organization,
            "block": self.block,
            "plot_number": number,
            "size": Decimal("120.00"),
            "plot_type": Plot.PlotType.RESIDENTIAL,
            "rate_per_sq_unit": Decimal("500.00"),
            "total_price": Decimal("60000.00"),
        }
        values.update(overrides)
        return Plot.objects.create(**values)

    def payload(self, **overrides):
        values = {
            "block": self.block.id,
            "plot_number": "A-102",
            "size": "125.50",
            "plot_type": "residential",
            "rate_per_sq_unit": "500.00",
            "total_price": "62750.00",
            "facing": "East",
        }
        values.update(overrides)
        return values

    def test_list_is_organization_scoped_and_paginated(self):
        self.make_plot("A-102")
        self.make_plot("A-103")
        response = self.client.get(self.list_url(), {"page": 1, "page_size": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])
        self.assertNotIn(self.foreign_plot.id, [item["id"] for item in response.data["results"]])

    def test_list_search_and_filters(self):
        commercial = self.make_plot("A-COM", plot_type=Plot.PlotType.COMMERCIAL, status=Plot.Status.BLOCKED)
        self.make_plot("B-101", block=self.other_block)
        self.assertEqual(self.client.get(self.list_url(), {"search": "COM"}).data["results"][0]["id"], commercial.id)
        self.assertEqual(self.client.get(self.list_url(), {"search": "A Block"}).data["count"], 2)
        self.assertEqual(self.client.get(self.list_url(), {"search": "B Block"}).data["count"], 1)
        self.assertEqual(self.client.get(self.list_url(), {"block": self.other_block.id}).data["count"], 1)
        self.assertEqual(self.client.get(self.list_url(), {"block": self.block.id, "status": "blocked"}).data["count"], 1)
        response = self.client.get(self.list_url(), {"block": self.block.id, "status": "blocked", "plot_type": "commercial"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], commercial.id)

    def test_invalid_filters_and_inconsistent_filter_combination_are_rejected(self):
        self.assertEqual(self.client.get(self.list_url(), {"status": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.list_url(), {"plot_type": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.list_url(), {"block": self.other_block.id, "status": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(self.list_url(), {"block": self.foreign_block.id}).status_code, 400)

    def test_create_assigns_organization_creator_and_default_status(self):
        response = self.client.post(self.list_url(), self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        plot = Plot.objects.get(pk=response.data["id"])
        self.assertEqual(plot.organization, self.organization)
        self.assertEqual(plot.created_by, self.user)
        self.assertEqual(plot.status, Plot.Status.AVAILABLE)

    def test_create_rejects_invalid_relationships_duplicate_and_numbers(self):
        self.assertEqual(self.client.post(self.list_url(), self.payload(block=self.foreign_block.id), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url(), self.payload(block=self.other_block.id), format="json").status_code, 201)
        self.assertEqual(self.client.post(self.list_url(), self.payload(plot_number=self.plot.plot_number), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url(), self.payload(plot_number="A-103", size="0"), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url(), self.payload(plot_number="A-104", rate_per_sq_unit="-1"), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.list_url(), self.payload(plot_number="A-105", total_price="-1"), format="json").status_code, 400)

    def test_create_rejects_status_and_impersonation_fields(self):
        response = self.client.post(self.list_url(), self.payload(plot_number="A-103", status="sold"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)
        response = self.client.post(self.list_url(), self.payload(plot_number="A-103", created_by=self.other_user.id), format="json")
        self.assertEqual(response.status_code, 400)

    def test_detail_is_scoped_to_organization(self):
        response = self.client.get(self.detail_url(self.plot))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.plot.id)
        self.assertEqual(self.client.get(self.detail_url(self.foreign_plot)).status_code, 404)
        self.assertEqual(self.client.get(reverse("inventory:plot-detail", args=[self.organization.slug, 999999])).status_code, 404)

    def test_patch_updates_metadata_but_not_protected_fields(self):
        response = self.client.patch(self.detail_url(self.plot), {"plot_number": "A-150", "facing": "North"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.plot_number, "A-150")
        self.assertEqual(self.client.patch(self.detail_url(self.plot), {"status": "sold"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.detail_url(self.plot), {"organization_id": self.other_organization.id}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.detail_url(self.plot), {"created_by": self.other_user.id}, format="json").status_code, 400)

    def test_patch_rejects_duplicate_mismatched_relationship_and_cross_tenant_access(self):
        duplicate = self.make_plot("A-102")
        self.assertEqual(self.client.patch(self.detail_url(duplicate), {"plot_number": self.plot.plot_number}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.detail_url(self.plot), {"block": self.foreign_block.id}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(self.detail_url(self.foreign_plot), {"facing": "South"}, format="json").status_code, 404)
