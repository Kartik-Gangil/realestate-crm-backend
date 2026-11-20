"""NFR-P12-01 / FR-P6-07 / FR-P6-08: recordings are served only to callers who may see the call."""
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.tests.downloads import assert_protected_download
from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from core.tests.samples import SAMPLE_MP3
from leads.models import FollowUpCall, Lead
from leads.serializers import follow_up_to_dict


class CallRecordingDownloadTests(TestCase):
    def setUp(self):
        self.organization = make_organization("calls")
        self.project = make_project(self.organization, "CALL-A")
        self.other_project = make_project(self.organization, "CALL-B")
        caller = make_member(self.organization, role="telecaller", projects=[self.project])
        colleague = make_member(self.organization, role="telecaller", projects=[self.project])
        admin = make_member(self.organization, role="admin", projects=[self.project])
        self.caller = caller.user
        self.colleague = colleague.user
        self.admin = admin.user
        lead = Lead.objects.create(organization=self.organization, project=self.project, first_name="Lead", phone="9000000031", assigned_membership=caller)
        self.call = FollowUpCall.objects.create(organization=self.organization, lead=lead, telecaller_membership=caller,
                                                called_at=timezone.now(), call_recording=SimpleUploadedFile("call.mp3", SAMPLE_MP3))
        self.silent = FollowUpCall.objects.create(organization=self.organization, lead=lead, telecaller_membership=caller, called_at=timezone.now())
        self.client = APIClient()

    def get(self, user, call=None, project=None):
        self.client.force_authenticate(user)
        url = f"/api/v1/organizations/calls/telecalling/calls/{(call or self.call).id}/recording/"
        return self.client.get(url, **project_request_kwargs(project or self.project))

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

    def test_call_recording_storage_stays_under_private_media_task_sec_001(self):
        backend_root = Path(settings.BASE_DIR).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_root = Path(self.call.call_recording.storage.location).resolve()
        stored_path = (storage_root / self.call.call_recording.name).resolve()
        self.assertEqual(storage_root, media_root)
        self.assertFalse(storage_root == backend_root or storage_root.is_relative_to(backend_root))
        self.assertTrue(stored_path.is_relative_to(media_root))
