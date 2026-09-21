from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership
from system_settings.master_data import ensure_call_dispositions


class CallDispositionRequiredApiTests(TestCase):
    """FR-P6-04: a manual call log requires a valid disposition."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="caller", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            first_name="Ravi",
            phone="9999999999",
            assigned_membership=self.membership,
        )
        ensure_call_dispositions(self.organization)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.log_url = reverse("leads:telecalling-call-log", args=[self.organization.slug])

    def test_rejected_log_does_not_create_or_mutate_call(self):
        for disposition in (None, "", "   ", "connected"):
            payload = {"lead_id": self.lead.id, "notes": "Must not persist"}
            if disposition is not None:
                payload["disposition"] = disposition
            response = self.client.post(self.log_url, payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            self.assertFalse(FollowUpCall.objects.exists())

    def test_valid_manual_log_persists_disposition(self):
        completed = self.client.post(self.log_url, {
            "lead_id": self.lead.id,
            "notes": "Customer was busy",
            "disposition": "busy",
        }, format="json")
        self.assertEqual(completed.status_code, 201, completed.data)
        self.assertEqual(FollowUpCall.objects.get().outcome, "busy")
