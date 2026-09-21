from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, FollowUpReminder, Lead
from organizations.models import Organization, OrganizationMembership
from system_settings.master_data import ensure_call_dispositions


class TelecallingFollowUpApiTests(TestCase):
    """API-P6-04: contract endpoint for creating telecalling follow-ups."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="api-p6-04", password="test-pass")
        self.other_user = user_model.objects.create_user(username="api-p6-04-other", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.other_organization = Organization.objects.create(name="Other", slug="other")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.other_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_user,
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.foreign_membership = OrganizationMembership.objects.create(
            organization=self.other_organization,
            user=get_user_model().objects.create_user(username="api-p6-04-foreign"),
            role=OrganizationMembership.Role.TELECALLER,
        )
        self.lead = Lead.objects.create(
            organization=self.organization,
            first_name="Assigned",
            phone="9111111111",
            assigned_membership=self.membership,
        )
        self.other_lead = Lead.objects.create(
            organization=self.organization,
            first_name="Other caller",
            phone="9222222222",
            assigned_membership=self.other_membership,
        )
        self.foreign_lead = Lead.objects.create(
            organization=self.other_organization,
            first_name="Foreign",
            phone="9333333333",
            assigned_membership=self.foreign_membership,
        )
        ensure_call_dispositions(self.organization)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("leads:telecalling-follow-ups", args=[self.organization.slug])

    def test_creates_scheduled_follow_up_and_phase14_reminder(self):
        follow_up_at = timezone.now() + timedelta(days=1)

        response = self.client.post(self.url, {
            "lead_id": self.lead.id,
            "note": "Call again tomorrow",
            "next_follow_up": follow_up_at.isoformat(),
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        call = FollowUpCall.objects.get(pk=response.data["id"])
        self.assertEqual(call.lead_id, self.lead.id)
        self.assertEqual(call.telecaller_membership_id, self.membership.id)
        self.assertEqual(call.outcome, "")
        self.assertIsNone(call.called_at)
        self.assertEqual(call.next_follow_up, follow_up_at)
        reminder = FollowUpReminder.objects.get(follow_up=call)
        self.assertEqual(reminder.scheduled_for, follow_up_at)
        self.assertEqual(reminder.recipient_membership_id, self.membership.id)

    def test_reuses_callers_existing_pending_attempt(self):
        call = FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.lead,
            telecaller_membership=self.membership,
        )

        response = self.client.post(self.url, {
            "lead_id": self.lead.id,
            "note": "Call tomorrow",
            "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(),
        }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["id"], call.id)
        self.assertEqual(FollowUpCall.objects.filter(lead=self.lead).count(), 1)
        call.refresh_from_db()
        self.assertEqual(call.outcome, "")
        self.assertIsNone(call.called_at)
        self.assertIsNotNone(call.next_follow_up)

    def test_validates_required_contract_fields_and_conditional_schedule(self):
        missing_lead = self.client.post(self.url, {"note": "Missing lead"}, format="json")
        missing_note = self.client.post(self.url, {"lead_id": self.lead.id}, format="json")
        missing_schedule = self.client.post(self.url, {
            "lead_id": self.lead.id,
            "note": "Interested",
        }, format="json")
        call_activity = self.client.post(self.url, {
            "lead_id": self.lead.id,
            "note": "Must use API-P6-06",
            "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(),
            "outcome": "interested",
            "called_at": timezone.now().isoformat(),
        }, format="json")

        self.assertEqual(missing_lead.status_code, 400)
        self.assertEqual(missing_note.status_code, 400)
        self.assertEqual(missing_schedule.status_code, 400)
        self.assertEqual(call_activity.status_code, 400)
        self.assertFalse(FollowUpCall.objects.filter(lead=self.lead).exists())

    def test_telecaller_cannot_create_follow_up_for_another_or_foreign_lead(self):
        payload = {
            "note": "Not assigned",
            "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(),
        }

        other = self.client.post(self.url, {"lead_id": self.other_lead.id, **payload}, format="json")
        foreign = self.client.post(self.url, {"lead_id": self.foreign_lead.id, **payload}, format="json")

        self.assertEqual(other.status_code, 404)
        self.assertEqual(foreign.status_code, 404)
        self.assertFalse(FollowUpCall.objects.exists())
