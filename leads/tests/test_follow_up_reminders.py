from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, FollowUpReminder, Lead
from leads.services import log_manual_call
from organizations.models import Organization, OrganizationMembership
from organizations.services import get_organization_access
from system_settings.master_data import ensure_call_dispositions


class FollowUpReminderTests(TestCase):
    """FR-P6-06: scheduled follow-ups emit durable Phase 14 reminder events."""

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

    def test_manual_log_creates_phase14_ready_reminder_atomically(self):
        follow_up_at = timezone.now() + timedelta(days=1)

        response = self.client.post(
            self.log_url,
            {
                "lead_id": self.lead.id,
                "disposition": "callback_later",
                "next_follow_up": follow_up_at.isoformat(),
                "notes": "Call after lunch.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        call = FollowUpCall.objects.get(pk=response.data["id"])
        reminder = FollowUpReminder.objects.get(follow_up=call)
        self.assertEqual(reminder.organization, self.organization)
        self.assertEqual(reminder.recipient_membership, self.membership)
        self.assertEqual(reminder.scheduled_for, follow_up_at)
        self.assertEqual(reminder.event_type, "telecalling.follow_up_due")
        self.assertEqual(reminder.status, FollowUpReminder.Status.PENDING)
        self.assertEqual(reminder.payload["lead_id"], self.lead.id)
        self.assertEqual(reminder.payload["follow_up_id"], call.id)
        call.refresh_from_db()
        self.assertFalse(call.reminder_sent)

    def test_unscheduled_disposition_does_not_create_reminder(self):
        response = self.client.post(
            self.log_url,
            {"lead_id": self.lead.id, "disposition": "busy", "notes": "Busy."},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        call = FollowUpCall.objects.get(pk=response.data["id"])
        self.assertFalse(FollowUpReminder.objects.filter(follow_up=call).exists())

    def test_reminder_failure_rolls_back_call_completion(self):
        access = get_organization_access(self.user, self.organization.slug)
        follow_up_at = timezone.now() + timedelta(days=1)

        with patch("leads.services.sync_follow_up_reminder", side_effect=RuntimeError("outbox unavailable")):
            with self.assertRaises(RuntimeError):
                log_manual_call(
                    access=access,
                    lead=self.lead,
                    disposition="interested",
                    notes="Interested.",
                    next_follow_up=follow_up_at,
                )

        self.assertFalse(FollowUpCall.objects.exists())
        self.assertFalse(FollowUpReminder.objects.exists())
