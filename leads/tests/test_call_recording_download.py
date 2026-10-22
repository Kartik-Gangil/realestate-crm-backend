"""NFR-P12-01 / FR-P6-07 / FR-P6-08: recordings are served only to callers who may see the call."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.samples import SAMPLE_MP3
from inventory.models import Project
from leads.models import FollowUpCall, Lead
from leads.serializers import follow_up_to_dict
from organizations.models import Organization, OrganizationMembership


class CallRecordingDownloadTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.organization = Organization.objects.create(name="Calls", slug="calls")
        self.project = Project.objects.create(organization=self.organization, name="Main", code="CALL-A")
        self.other_project = Project.objects.create(organization=self.organization, name="Other", code="CALL-B")
        self.caller = users.create_user(username="rec-caller", password="pw-123456")
        self.colleague = users.create_user(username="rec-colleague", password="pw-123456")
        self.admin = users.create_user(username="rec-admin", password="pw-123456")
        caller = OrganizationMembership.objects.create(organization=self.organization, user=self.caller, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.colleague, role=OrganizationMembership.Role.TELECALLER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN)
        lead = Lead.objects.create(organization=self.organization, project=self.project, first_name="Lead", phone="9000000031", assigned_membership=caller)
        self.call = FollowUpCall.objects.create(organization=self.organization, lead=lead, telecaller_membership=caller,
                                                called_at=timezone.now(), call_recording=SimpleUploadedFile("call.mp3", SAMPLE_MP3))
        self.silent = FollowUpCall.objects.create(organization=self.organization, lead=lead, telecaller_membership=caller, called_at=timezone.now())
        self.client = APIClient()

    def get(self, user, call=None, project=None):
        self.client.force_authenticate(user)
        url = f"/api/v1/organizations/calls/telecalling/calls/{(call or self.call).id}/recording/"
        return self.client.get(url, HTTP_X_PROJECT_ID=str((project or self.project).id))

    def test_the_caller_and_an_admin_can_download_the_recording(self):
        assert_protected_download(self, self.get(self.caller), SAMPLE_MP3, "audio/mpeg")
        assert_protected_download(self, self.get(self.admin), SAMPLE_MP3, "audio/mpeg")

    def test_authentication_is_required(self):
        url = f"/api/v1/organizations/calls/telecalling/calls/{self.call.id}/recording/"
        self.assertEqual(self.client.get(url, HTTP_X_PROJECT_ID=str(self.project.id)).status_code, 401)

    def test_another_telecaller_and_another_project_get_404(self):
        self.assertEqual(self.get(self.colleague).status_code, 404)
        self.assertEqual(self.get(self.admin, project=self.other_project).status_code, 404)

    def test_a_call_without_a_recording_is_404(self):
        self.assertEqual(self.get(self.caller, self.silent).status_code, 404)

    def test_follow_up_output_uses_the_endpoint_path(self):
        self.assertEqual(follow_up_to_dict(self.call)["call_recording"],
                         f"/api/v1/organizations/calls/telecalling/calls/{self.call.id}/recording/")
        self.assertIsNone(follow_up_to_dict(self.silent)["call_recording"])
