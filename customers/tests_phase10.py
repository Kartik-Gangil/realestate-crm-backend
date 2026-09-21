from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import Lead, Sitevisit
from organizations.models import Organization, OrganizationMembership

from .models import Customer


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
class Phase10CustomerTests(TestCase):
    """FR-P10-01..06, DM-P10-01/02, API-P10-01..04, NFR-P10-01."""

    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="customer-manager", password="password123")
        self.telecaller = user_model.objects.create_user(username="customer-telecaller", password="password123")
        self.organization = Organization.objects.create(name="Customer Org", slug="customer-org")
        self.manager_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER,
        )
        self.telecaller_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER,
        )
        self.lead = Lead.objects.create(
            organization=self.organization, first_name="Asha", last_name="Sharma",
            phone="9999999999", email="asha@example.com", assigned_membership=self.telecaller_membership,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = reverse("customers:customer-list", args=[self.organization.slug])

    def test_lead_conversion_auto_creates_customer_and_manual_creation_rejects_duplicates(self):
        self.lead.status = "converted"
        self.lead.save(update_fields=["status", "updated_at"])
        customer = Customer.objects.get(lead=self.lead)
        self.assertEqual(customer.phone, self.lead.phone)
        duplicate = self.client.post(self.url, {
            "full_name": "Another", "phone": self.lead.phone,
        }, format="json")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.data["existing_customer_id"], customer.id)

    def test_customer_status_is_non_destructive_and_role_scoped(self):
        response = self.client.post(self.url, {"full_name": "Ravi Kumar", "phone": "8888888888", "email": "ravi@example.com"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        customer_id = response.data["id"]
        update = self.client.patch(reverse("customers:customer-detail", args=[self.organization.slug, customer_id]), {"status": "blacklisted", "status_reason": "Duplicate fraud profile"}, format="json")
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(Customer.objects.get(pk=customer_id).status, Customer.Status.BLACKLISTED)
        self.assertEqual(self.client.delete(reverse("customers:customer-detail", args=[self.organization.slug, customer_id])).status_code, 405)

    def test_360_aggregates_bookings_payments_documents_and_notes(self):
        customer = Customer.objects.create(organization=self.organization, full_name="Asha Sharma", phone="7777777777", lead=self.lead)
        note = self.client.post(reverse("customers:customer-notes", args=[self.organization.slug, customer.id]), {"note_text": "Follow up completed"}, format="json")
        self.assertEqual(note.status_code, 201, note.data)
        response = self.client.get(reverse("customers:customer-360", args=[self.organization.slug, customer.id]))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["customer"]["id"], customer.id)
        self.assertEqual(response.data["summary"]["notes"], 1)
        self.assertIn("timeline", response.data)

    def test_assigned_telecaller_can_view_only_assigned_customer(self):
        customer = Customer.objects.create(organization=self.organization, full_name="Asha Sharma", phone="7777777777", lead=self.lead)
        self.client.force_authenticate(self.telecaller)
        response = self.client.get(reverse("customers:customer-360", args=[self.organization.slug, customer.id]))
        self.assertEqual(response.status_code, 200)
        other_lead = Lead.objects.create(organization=self.organization, first_name="Other", phone="6666666666")
        other = Customer.objects.create(organization=self.organization, full_name="Other", phone=other_lead.phone, lead=other_lead)
        self.assertEqual(self.client.get(reverse("customers:customer-detail", args=[self.organization.slug, other.id])).status_code, 403)
