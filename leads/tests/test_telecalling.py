from datetime import timedelta
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from core.tests.samples import FORGED_EXE, FORGED_HTML, SAMPLE_AAC, SAMPLE_M4A, SAMPLE_MP3, SAMPLE_MP3_FRAME, SAMPLE_PDF, SAMPLE_WAV
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from leads.models import FollowUpCall, Lead
from inventory.models import Project
from organizations.models import Organization, OrganizationMembership


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class TelecallingApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="caller", password="test-pass")
        self.other = User.objects.create_user(username="other", password="test-pass")
        self.admin = User.objects.create_user(username="admin", password="test-pass")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.organization, name="Main", code="MAIN")
        self.other_project = Project.objects.create(organization=self.organization, name="Other", code="OTHER")
        self.membership = OrganizationMembership.objects.create(organization=self.organization, user=self.user, role=OrganizationMembership.Role.TELECALLER)
        self.other_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.other, role=OrganizationMembership.Role.TELECALLER)
        self.admin_membership = OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN)
        self.assigned = Lead.objects.create(organization=self.organization, project=self.project, first_name="Assigned", phone="9000000001", assigned_membership=self.membership)
        self.hidden = Lead.objects.create(organization=self.organization, project=self.project, first_name="Hidden", phone="9000000002", assigned_membership=self.other_membership)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.credentials(HTTP_X_PROJECT_ID=str(self.project.id))

    def test_queue_is_scoped_to_active_telecaller(self):
        response = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["results"]], [self.assigned.id])

    def test_admin_queue_contains_all_leads_with_assignee_and_status(self):
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="contacted",
            outcome="connected",
            called_at=timezone.now(),
        )
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.data["results"]}, {self.assigned.id, self.hidden.id})
        assigned = next(item for item in response.data["results"] if item["id"] == self.assigned.id)
        self.assertEqual(assigned["assigned_membership"], self.membership.user.get_full_name())
        self.assertEqual(assigned["status"], "contacted")

    def test_queue_is_scoped_to_active_project(self):
        other_project_lead = Lead.objects.create(
            organization=self.organization,
            project=self.other_project,
            first_name="Other project lead",
            phone="9000000003",
            assigned_membership=self.membership,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.assigned.id, [item["id"] for item in response.data["results"]])
        self.assertNotIn(other_project_lead.id, [item["id"] for item in response.data["results"]])

    def test_pending_assignment_takes_precedence_over_previous_contacted_status(self):
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="contacted",
            outcome="Interested",
            called_at=timezone.now(),
        )
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="new",
            called_at=None,
        )

        response = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))

        self.assertEqual(response.status_code, 200)
        assigned = next(item for item in response.data["results"] if item["id"] == self.assigned.id)
        self.assertEqual(assigned["pending_attempts"], 1)
        self.assertEqual(assigned["status"], "new")

    def test_reassigning_a_lead_does_not_create_duplicate_pending_attempts(self):
        self.client.force_authenticate(self.admin)
        url = reverse("leads:assign-lead", args=[self.organization.slug, self.assigned.id])
        payload = {"telecaller_membership": self.membership.id}

        first = self.client.patch(url, payload, format="json")
        second = self.client.patch(url, payload, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            FollowUpCall.objects.filter(
                lead=self.assigned,
                telecaller_membership=self.membership,
                called_at__isnull=True,
            ).count(),
            1,
        )

    def test_telecaller_queue_ignores_previous_assignee_pending_attempts(self):
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.other_membership,
            status="new",
            called_at=None,
        )
        FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="contacted",
            outcome="Interested",
            called_at=timezone.now(),
        )

        response = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))

        self.assertEqual(response.status_code, 200)
        assigned = next(item for item in response.data["results"] if item["id"] == self.assigned.id)
        self.assertEqual(assigned["pending_attempts"], 0)
        self.assertEqual(assigned["status"], "contacted")

    def test_lead_detail_keeps_lifecycle_status_separate_from_call_disposition(self):
        older = FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="contacted",
            outcome="connected",
            note="Initial conversation",
            called_at=timezone.now() - timedelta(minutes=10),
        )
        newer = FollowUpCall.objects.create(
            organization=self.organization,
            lead=self.assigned,
            telecaller_membership=self.membership,
            status="won",
            outcome="Already Purchased",
            note="Customer completed purchase",
            called_at=timezone.now(),
        )

        response = self.client.get(reverse("leads:detail", args=[self.organization.slug, self.assigned.id]))

        self.assertEqual(response.status_code, 200)
        calls = response.data["follow_up_calls"]
        self.assertEqual([call["id"] for call in calls], [newer.id, older.id])
        self.assertEqual(calls[0]["status"], "won")
        self.assertEqual(calls[0]["disposition"], "Already Purchased")
        self.assertEqual(calls[0]["outcome"], "Already Purchased")
        self.assertEqual(calls[0]["note"], "Customer completed purchase")
        self.assertEqual(calls[0]["notes"], "Customer completed purchase")

    def test_manual_call_log_validates_disposition_and_follow_up(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        invalid = self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Busy", "notes": "busy"}, format="json")
        self.assertEqual(invalid.status_code, 201)
        invalid_follow_up = self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Callback Later", "notes": "call back"}, format="json")
        self.assertEqual(invalid_follow_up.status_code, 400)
        invalid_disposition = self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Unknown", "notes": "x"}, format="json")
        self.assertEqual(invalid_disposition.status_code, 400)

    def test_logging_a_new_pending_lead_advances_it_to_contacted(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        response = self.client.post(url, {
            "lead_id": self.assigned.id,
            "disposition": "Busy",
            "status": "new",
            "notes": "Call completed but customer was busy",
        }, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "contacted")
        self.assertEqual(FollowUpCall.objects.get(lead=self.assigned).status, "contacted")

    def test_manual_call_log_accepts_recording_and_updates_follow_up(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        recording = SimpleUploadedFile("call.mp3", SAMPLE_MP3, content_type="audio/mpeg")
        response = self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Interested", "notes": "warm lead", "next_follow_up": (timezone.now() + timedelta(days=1)).isoformat(), "recording": recording}, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(FollowUpCall.objects.filter(lead=self.assigned, called_at__isnull=False).count(), 1)

    def test_manual_call_log_preserves_disposition_and_requested_status_after_refresh(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        response = self.client.post(url, {
            "lead_id": self.assigned.id,
            "disposition": "Switched Off",
            "status": "contacted",
            "notes": "No answer from phone",
        }, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["disposition"], "Switched Off")
        self.assertEqual(response.data["outcome"], "Switched Off")
        self.assertEqual(response.data["status"], "contacted")

        queue = self.client.get(reverse("telecalling-queue", args=[self.organization.slug]))
        assigned = next(item for item in queue.data["results"] if item["id"] == self.assigned.id)
        self.assertEqual(assigned["status"], "contacted")

    def test_all_phase_six_dispositions_are_accepted_and_returned_exactly(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        dispositions = ["Interested", "Callback Later", "Busy", "No Answer", "Switched Off", "Wrong Number", "DND", "Already Purchased"]
        for disposition in dispositions:
            payload = {"lead_id": self.assigned.id, "disposition": disposition, "status": "contacted", "notes": disposition}
            if disposition in {"Interested", "Callback Later"}:
                payload["next_follow_up"] = (timezone.now() + timedelta(days=1)).isoformat()
            response = self.client.post(url, payload, format="json")
            self.assertEqual(response.status_code, 201, disposition)
            self.assertEqual(response.data["disposition"], disposition)

    def test_recording_over_25mb_is_rejected(self):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        recording = SimpleUploadedFile("call.mp3", b"x" * (25 * 1024 * 1024 + 1), content_type="audio/mpeg")
        response = self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Busy", "notes": "busy", "recording": recording}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def log_call(self, name, content):
        url = reverse("telecalling-call-log", args=[self.organization.slug])
        recording = SimpleUploadedFile(name, content, content_type="audio/mpeg")
        return self.client.post(url, {"lead_id": self.assigned.id, "disposition": "Busy", "notes": "busy", "recording": recording}, format="multipart")

    def test_forged_recording_is_rejected_task_sec_001(self):
        for name, content in (("call.mp3", FORGED_HTML), ("call.m4a", SAMPLE_PDF), ("call.wav", FORGED_EXE)):
            response = self.log_call(name, content)
            self.assertEqual(response.status_code, 400)
            self.assertIn("recording", response.data)
        self.assertFalse(FollowUpCall.objects.filter(lead=self.assigned, called_at__isnull=False).exists())

    def test_each_allowed_recording_format_is_accepted_task_sec_001(self):
        for name, content in (("call.mp3", SAMPLE_MP3_FRAME), ("call.wav", SAMPLE_WAV), ("call.m4a", SAMPLE_M4A), ("call.aac", SAMPLE_AAC)):
            self.assertEqual(self.log_call(name, content).status_code, 201)
