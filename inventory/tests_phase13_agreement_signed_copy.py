import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import Agreement, Block, Plot, PlotBooking, AgreementSignedDocument, Project
from .phase5_services import create_agreement, transition_agreement
from core.tests.samples import FORGED_EXE, FORGED_HTML, SAMPLE_PDF, SAMPLE_PNG


class AgreementSignedCopyTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="legal@example.com", email="legal@example.com", password="password123")
        self.organization = Organization.objects.create(name="Acme", slug="acme")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role=OrganizationMembership.Role.ADMIN)
        project = Project.objects.create(organization=self.organization, name="Green", code="GREEN")
        block = Block.objects.create(organization=self.organization, project=project, name="A", code="A")
        plot = Plot.objects.create(organization=self.organization, project=project, block=block, plot_number="A-101", size=Decimal("100"), total_price=Decimal("1000"), status=Plot.Status.BOOKED)
        lead = Lead.objects.create(organization=self.organization, project=project, first_name="Ada", phone="9999999999")
        self.booking = PlotBooking.objects.create(organization=self.organization, lead=lead, plot=plot, status=PlotBooking.Status.CONFIRMED, final_price=Decimal("1000"), created_by=self.user)
        self.agreement = create_agreement(booking=self.booking, agreement_number="AGR-1", created_by=self.user)
        transition_agreement(agreement=self.agreement, status=Agreement.Status.READY)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.defaults["HTTP_X_PROJECT_ID"] = str(project.id)

    def signed_upload(self, name="signed-agreement.pdf", content=SAMPLE_PDF):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def upload_url(self):
        return reverse("inventory:agreement-upload-signed", args=[self.organization.slug, self.agreement.id])

    def download_url(self):
        return reverse("inventory:agreement-download-signed", args=[self.organization.slug, self.agreement.id])

    def test_signed_transition_requires_a_signed_copy(self):
        with self.assertRaises(ValidationError):
            transition_agreement(agreement=self.agreement, status=Agreement.Status.SIGNED)

    def test_upload_retains_metadata_and_allows_signed_transition(self):
        response = self.client.post(self.upload_url(), {"file": self.signed_upload()}, format="multipart")
        self.assertEqual(response.status_code, 201)
        document = AgreementSignedDocument.objects.get(agreement=self.agreement)
        self.assertEqual(document.original_filename, "signed-agreement.pdf")
        self.assertEqual(document.content_type, "application/pdf")
        self.assertEqual(document.file_size_bytes, len(SAMPLE_PDF))
        self.assertEqual(document.uploaded_by, self.user)
        self.assertTrue(response.data["has_signed_file"])

        transition_agreement(agreement=self.agreement, status=Agreement.Status.SIGNED)
        self.assertEqual(Agreement.objects.get(pk=self.agreement.pk).status, Agreement.Status.SIGNED)

    def test_replacement_preserves_previous_copy_history(self):
        self.client.post(self.upload_url(), {"file": self.signed_upload("first.pdf", SAMPLE_PDF)}, format="multipart")
        response = self.client.post(self.upload_url(), {"file": self.signed_upload("replacement.pdf", SAMPLE_PDF)}, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AgreementSignedDocument.objects.filter(agreement=self.agreement).count(), 2)
        self.assertEqual(AgreementSignedDocument.objects.filter(agreement=self.agreement, superseded_at__isnull=True).count(), 1)
        self.assertEqual(AgreementSignedDocument.objects.get(agreement=self.agreement, superseded_at__isnull=True).original_filename, "replacement.pdf")

    def test_signed_copy_can_be_downloaded(self):
        self.client.post(self.upload_url(), {"file": self.signed_upload()}, format="multipart")
        response = self.client.get(reverse("inventory:agreement-download-signed", args=[self.organization.slug, self.agreement.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response["Content-Disposition"])

    def test_forged_signed_copy_is_rejected_task_sec_001(self):
        for name, content in (("signed.pdf", FORGED_HTML), ("signed.png", FORGED_EXE)):
            response = self.client.post(self.upload_url(), {"file": self.signed_upload(name, content)}, format="multipart")
            self.assertEqual(response.status_code, 400)
            self.assertIn("file", response.data)
        self.assertFalse(AgreementSignedDocument.objects.filter(agreement=self.agreement).exists())

    def test_signed_copy_stores_the_detected_type_task_sec_001(self):
        upload = SimpleUploadedFile("signed.png", SAMPLE_PNG, content_type="text/html")
        self.assertEqual(self.client.post(self.upload_url(), {"file": upload}, format="multipart").status_code, 201)
        self.assertEqual(AgreementSignedDocument.objects.get(agreement=self.agreement).content_type, "image/png")

    def test_signed_copy_download_is_a_protected_attachment_task_sec_001(self):
        self.client.post(self.upload_url(), {"file": self.signed_upload()}, format="multipart")
        AgreementSignedDocument.objects.filter(agreement=self.agreement).update(content_type="text/html")
        response = self.client.get(self.download_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, SAMPLE_PDF)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_signed_copy_download_requires_authentication_task_sec_001(self):
        self.client.post(self.upload_url(), {"file": self.signed_upload()}, format="multipart")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.download_url()).status_code, 401)
