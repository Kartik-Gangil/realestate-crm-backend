from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from organizations.models import Organization, OrganizationMembership
from system_settings.master_data import ensure_call_dispositions


class FollowUpRequiredDispositionApiTests(TestCase):
    """FR-P6-05: Interested/Callback Later require follow-up date and time."""

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

    def pending_call(self):
        return FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.lead,
            telecaller_membership=self.membership,
        )

    def test_interested_and_callback_later_require_and_persist_follow_up(self):
        follow_up_at = timezone.now() + timedelta(days=1)
        for disposition in ("interested", "callback_later"):
            call = self.pending_call()
            missing = self.client.post(
                self.log_url,
                {"lead_id": self.lead.id, "disposition": disposition, "notes": "Follow up."},
                format="json",
            )
            self.assertEqual(missing.status_code, 400, missing.data)
            call.refresh_from_db()
            self.assertIsNone(call.called_at)
            self.assertIsNone(call.next_follow_up)

            completed = self.client.post(
                self.log_url,
                {
                    "lead_id": self.lead.id,
                    "disposition": disposition,
                    "notes": "Follow up.",
                    "next_follow_up": follow_up_at.isoformat(),
                },
                format="json",
            )
            self.assertEqual(completed.status_code, 200, completed.data)
            call.refresh_from_db()
            self.assertEqual(call.next_follow_up, follow_up_at)
            self.assertIsNotNone(call.called_at)

    def test_malformed_follow_up_is_rejected_without_closing_call(self):
        call = self.pending_call()
        response = self.client.post(
            self.log_url,
            {
                "lead_id": self.lead.id,
                "disposition": "interested",
                "notes": "Follow up.",
                "next_follow_up": "tomorrow morning",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        call.refresh_from_db()
        self.assertIsNone(call.called_at)
        self.assertIsNone(call.next_follow_up)

    def test_other_disposition_can_end_without_follow_up(self):
        call = self.pending_call()
        response = self.client.post(
            self.log_url,
            {"lead_id": self.lead.id, "disposition": "busy", "notes": "Busy."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        call.refresh_from_db()
        self.assertIsNotNone(call.called_at)
        self.assertIsNone(call.next_follow_up)

    def test_manual_log_uses_editable_call_timestamp(self):
        call_timestamp = timezone.now().isoformat()
        follow_up_at = (timezone.now() + timedelta(hours=4)).isoformat()

        completed = self.client.post(
            self.log_url,
            {
                "lead_id": self.lead.id,
                "notes": "Interested",
                "call_timestamp": call_timestamp,
                "disposition": "interested",
                "next_follow_up": follow_up_at,
            },
            format="json",
        )
        self.assertEqual(completed.status_code, 201, completed.data)
        call = FollowUpCall.objects.get(pk=completed.data["id"])
        self.assertEqual(call.called_at.isoformat(), call_timestamp)
        self.assertEqual(call.next_follow_up.isoformat(), follow_up_at)
