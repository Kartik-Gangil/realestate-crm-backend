import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, FollowUpReminder, Lead, LeadStatusHistory
from organizations.models import Organization, OrganizationMembership
from system_settings.master_data import ensure_call_dispositions
from system_settings.models import AuditLog


class ManualCallLogApiTests(TestCase):
    """FR-P6-02/04/05/06/08 and API-P6-06 manual call-log contract."""

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="manual-caller", password="test-pass")
        self.other_user = user_model.objects.create_user(username="other-caller", password="test-pass")
        self.manager_user = user_model.objects.create_user(username="call-manager", password="test-pass")
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
        self.manager_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.manager_user,
            role=OrganizationMembership.Role.MANAGER,
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
        ensure_call_dispositions(self.organization)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("leads:telecalling-call-log", args=[self.organization.slug])

    def tearDown(self):
        self.settings_override.disable()
        self.media_dir.cleanup()

    def test_manual_log_defaults_timestamp_and_writes_audit_record(self):
        submitted_at = timezone.now().replace(microsecond=0)

        with patch("leads.services.timezone.now", return_value=submitted_at):
            response = self.client.post(
                self.url,
                {
                    "lead_id": self.lead.id,
                    "disposition": "busy",
                    "notes": "Customer asked to call after work.",
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 201, response.data)
        call = FollowUpCall.objects.get(pk=response.data["id"])
        self.assertEqual(call.lead_id, self.lead.id)
        self.assertEqual(call.telecaller_membership_id, self.membership.id)
        self.assertEqual(call.outcome, "busy")
        self.assertEqual(call.note, "Customer asked to call after work.")
        self.assertEqual(call.called_at, submitted_at)
        self.assertFalse(hasattr(call, "started_at"))
        self.assertFalse(hasattr(call, "duration_seconds"))
        self.assertEqual(response.data["disposition"], "busy")
        self.assertEqual(response.data["notes"], "Customer asked to call after work.")
        self.assertEqual(response.data["call_timestamp"], submitted_at.isoformat())
        self.assertIsNone(response.data["call_recording_url"])
        self.assertTrue(
            AuditLog.objects.filter(
                organization=self.organization,
                actor=self.user,
                module="telecalling",
                action="manual_call_logged",
                target_id=str(call.id),
            ).exists()
        )

    def test_disposition_auto_updates_lead_status_and_records_history(self):
        response = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "interested",
                "notes": "Customer wants a site visit.",
                "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "interested")
        history = list(LeadStatusHistory.objects.filter(lead=self.lead).order_by("id"))
        self.assertEqual([(item.old_status, item.new_status) for item in history], [
            ("new", "contacted"),
            ("contacted", "interested"),
        ])
        self.assertTrue(all(item.changed_by_id == self.user.id for item in history))

    def test_non_advancing_disposition_does_not_regress_lead_status(self):
        self.lead.status = "interested"
        self.lead.save(update_fields=["status"])

        response = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "busy",
                "notes": "Customer was unavailable.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "interested")
        self.assertFalse(LeadStatusHistory.objects.filter(lead=self.lead).exists())

    def test_editable_timestamp_and_allowed_recording_are_saved(self):
        call_timestamp = timezone.now().replace(microsecond=0) - timedelta(hours=2)
        recording = SimpleUploadedFile("customer-call.m4a", b"audio-data", content_type="audio/mp4")

        response = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "no_answer",
                "notes": "No response.",
                "call_timestamp": call_timestamp.isoformat(),
                "call_recording": recording,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        call = FollowUpCall.objects.get(pk=response.data["id"])
        self.assertEqual(call.called_at, call_timestamp)
        self.assertTrue(call.call_recording.name.endswith(".m4a"))
        self.assertIn("call-recordings/org/", call.call_recording.name)
        self.assertTrue(response.data["call_recording_url"])

    def test_callback_later_requires_follow_up_and_creates_reminder(self):
        missing = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "callback_later",
                "notes": "Call tomorrow.",
            },
            format="multipart",
        )

        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertIn("next_follow_up", missing.data)
        self.assertFalse(FollowUpCall.objects.filter(lead=self.lead).exists())

        follow_up_at = timezone.now() + timedelta(days=1)
        completed = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "callback_later",
                "notes": "Call tomorrow.",
                "next_follow_up": follow_up_at.isoformat(),
            },
            format="multipart",
        )

        self.assertEqual(completed.status_code, 201, completed.data)
        call = FollowUpCall.objects.get(pk=completed.data["id"])
        self.assertEqual(call.next_follow_up, follow_up_at)
        reminder = FollowUpReminder.objects.get(follow_up=call)
        self.assertEqual(reminder.scheduled_for, follow_up_at)
        self.assertEqual(reminder.recipient_membership_id, self.membership.id)

    def test_disposition_notes_and_recording_rules_are_enforced(self):
        cases = (
            ({"lead_id": self.lead.id, "notes": "Missing disposition"}, "disposition"),
            ({"lead_id": self.lead.id, "disposition": "unknown", "notes": "Invalid"}, "disposition"),
            ({"lead_id": self.lead.id, "disposition": "busy"}, "notes"),
        )
        for payload, field in cases:
            with self.subTest(field=field, payload=payload):
                response = self.client.post(self.url, payload, format="multipart")
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data)

        bad_extension = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "busy",
                "notes": "Invalid file.",
                "call_recording": SimpleUploadedFile("call.txt", b"audio", content_type="audio/mpeg"),
            },
            format="multipart",
        )
        self.assertEqual(bad_extension.status_code, 400, bad_extension.data)
        self.assertIn("call_recording", bad_extension.data)

        bad_content_type = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "busy",
                "notes": "Invalid MIME.",
                "call_recording": SimpleUploadedFile("call.mp3", b"audio", content_type="text/plain"),
            },
            format="multipart",
        )
        self.assertEqual(bad_content_type.status_code, 400, bad_content_type.data)
        self.assertIn("call_recording", bad_content_type.data)

        with patch("leads.services.MAX_CALL_RECORDING_SIZE_BYTES", 4):
            too_large = self.client.post(
                self.url,
                {
                    "lead_id": self.lead.id,
                    "disposition": "busy",
                    "notes": "Too large.",
                    "call_recording": SimpleUploadedFile("call.mp3", b"12345", content_type="audio/mpeg"),
                },
                format="multipart",
            )
        self.assertEqual(too_large.status_code, 400, too_large.data)
        self.assertIn("call_recording", too_large.data)
        self.assertFalse(FollowUpCall.objects.filter(lead=self.lead).exists())

    def test_only_assigned_telecaller_can_log_call(self):
        unassigned = self.client.post(
            self.url,
            {
                "lead_id": self.other_lead.id,
                "disposition": "busy",
                "notes": "Not assigned.",
            },
            format="multipart",
        )
        self.assertEqual(unassigned.status_code, 404)

        self.client.force_authenticate(self.manager_user)
        manager = self.client.post(
            self.url,
            {
                "lead_id": self.lead.id,
                "disposition": "busy",
                "notes": "Manager cannot submit telecaller logs.",
            },
            format="multipart",
        )
        self.assertEqual(manager.status_code, 403)
        self.assertFalse(FollowUpCall.objects.exists())

    def test_obsolete_start_and_end_session_routes_are_removed(self):
        base = f"/api/v1/organizations/{self.organization.slug}/telecalling/calls"
        start = self.client.post(f"{base}/start/", {"lead_id": self.lead.id}, format="json")
        end = self.client.post(f"{base}/end/", {"call_id": 1, "disposition": "busy"}, format="json")

        self.assertEqual(start.status_code, 404)
        self.assertEqual(end.status_code, 404)
