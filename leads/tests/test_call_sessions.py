from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership


class ObsoleteCallSessionApiTests(TestCase):
    """FR-P6-02/08: live start/end call sessions are unavailable."""

    def setUp(self):
        user_model = get_user_model()
        self.caller_user = user_model.objects.create_user(username="caller", password="test-pass")
        self.other_user = user_model.objects.create_user(username="other", password="test-pass")
        self.manager_user = user_model.objects.create_user(username="manager", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.caller = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.caller_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.other_caller = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.manager = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager_user,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            first_name="Ravi",
            phone="9999999999",
            assigned_membership=self.caller,
        )
        self.pending_attempt = FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.lead,
            telecaller_membership=self.caller,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.caller_user)
        self.log_url = reverse("leads:telecalling-call-log", args=[self.organization.slug])
        self.calls_base = f"/api/v1/organizations/{self.organization.slug}/telecalling/calls"

    def test_start_route_is_removed(self):
        response = self.client.post(
            f"{self.calls_base}/start/", {"lead_id": self.lead.id}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_end_route_is_removed(self):
        response = self.client.post(
            f"{self.calls_base}/end/", {"call_id": self.pending_attempt.id}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_model_has_no_live_session_or_duration_fields(self):
        field_names = {field.name for field in FollowUpCall._meta.fields}
        self.assertNotIn("started_at", field_names)
        self.assertNotIn("duration_seconds", field_names)

    def test_manual_log_is_the_available_call_submission_route(self):
        response = self.client.post(self.log_url, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lead_id", response.data)

    def test_pending_queue_attempt_has_no_connection_state(self):
        self.assertIsNone(self.pending_attempt.called_at)
        self.assertEqual(self.pending_attempt.outcome, "")
