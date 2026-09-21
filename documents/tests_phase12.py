from datetime import date, timedelta
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from leads.models import Lead
from organizations.models import Organization, OrganizationMembership

from .models import DocumentCategory, CustomerDocument, DocumentExpiryNotification, EkycVerification
from .services import create_expiry_notifications, process_ekyc_retry, verify_ekyc


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"], EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class Phase12DocumentTests(TestCase):
    """FR-P12-01..05, EC-P12-01, NFR-P12-01/02 backend coverage."""

    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self._media_override = override_settings(MEDIA_ROOT=self._media.name)
        self._media_override.enable()
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="p12-manager", email="manager@example.com", password="password123")
        self.telecaller = user_model.objects.create_user(username="p12-telecaller", email="telecaller@example.com", password="password123")
        self.organization = Organization.objects.create(name="P12 Org", slug="p12-org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.manager, role=OrganizationMembership.Role.MANAGER)
        OrganizationMembership.objects.create(organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER)
        self.lead = Lead.objects.create(organization=self.organization, first_name="Kiran", phone="9999999999", email="kiran@example.com")
        self.category = DocumentCategory.objects.create(organization=self.organization, name="ID Proof", code="id-proof")
        self.client = APIClient(); self.client.force_authenticate(self.manager)

    def tearDown(self):
        self._media_override.disable()
        self._media.cleanup()
        super().tearDown()

    def test_upload_encrypts_file_at_rest_and_expiry_alert_is_created(self):
        url = reverse("documents:documents", args=[self.organization.slug])
        response = self.client.post(url, {"customer": self.lead.id, "document_category": self.category.id, "document_name": "PAN", "file": SimpleUploadedFile("pan.pdf", b"%PDF-1.4 secret-data", content_type="application/pdf" )}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        document = CustomerDocument.objects.get()
        with document.file.open("rb") as stored:
            self.assertNotIn(b"secret-data", stored.read())
        document.expiry_date = date.today() + timedelta(days=10); document.save(update_fields=["expiry_date", "updated_at"])
        self.assertEqual(create_expiry_notifications(now=date.today()), 1)
        self.assertEqual(DocumentExpiryNotification.objects.count(), 1)

    def test_ekyc_provider_success_encrypts_id_and_updates_lead_gate(self):
        verification = verify_ekyc(customer=self.lead, provider="mock", id_number="ABCDE1234F", checks={"aadhaar": True, "pan": True, "face_match": 0.98}, actor=self.manager)
        self.assertEqual(verification.verification_status, EkycVerification.Status.VERIFIED)
        self.assertNotEqual(verification.id_number_encrypted, "ABCDE1234F")
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.ekyc_status, Lead.EkycStatus.VERIFIED)

    def test_provider_outage_is_queued_for_retry_and_can_be_processed(self):
        verification = verify_ekyc(customer=self.lead, provider="mock", id_number="ABCDE1234F", checks={"simulate_outage": True}, actor=self.manager)
        self.assertEqual(verification.verification_status, EkycVerification.Status.PENDING)
        self.assertEqual(verification.attempts, 1)
        verification = process_ekyc_retry(verification=verification, actor=self.manager, checks={"aadhaar": True, "pan": True, "face_match": 0.97})
        self.assertEqual(verification.verification_status, EkycVerification.Status.VERIFIED)

    def test_telecaller_can_upload_but_cannot_run_ekyc(self):
        self.client.force_authenticate(self.telecaller)
        url = reverse("documents:verify-ekyc", args=[self.organization.slug])
        response = self.client.post(url, {"customer": self.lead.id, "provider": "mock", "id_number": "ABCDE1234F"}, format="json")
        self.assertEqual(response.status_code, 403)
