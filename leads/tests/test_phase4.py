import csv
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership, Project
from system_settings.master_data import ensure_lead_sources

from leads.imports import process_import_batch
from leads.models import Lead, LeadImportBatch
from leads.duplicates import duplicate_score, normalize_phone


class Phase4LeadAcquisitionTests(TestCase):
    """PHASE 4: FR-P4-01..FR-P4-06, NFR-P4-01/NFR-P4-02, API-P4-01..API-P4-06."""

    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="phase4-admin@example.test", email="phase4-admin@example.test", password="Valid-password-1!"
        )
        self.telecaller = user_model.objects.create_user(
            username="phase4-telecaller@example.test", email="phase4-telecaller@example.test", password="Valid-password-1!"
        )
        self.organization = Organization.objects.create(name="Phase 4 Realty", slug="phase4-realty")
        self.project = Project.objects.create(organization=self.organization, name="Phase 4 Project", code="P4-PROJECT")
        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.admin, role=OrganizationMembership.Role.ADMIN
        )
        self.telecaller_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.telecaller, role=OrganizationMembership.Role.TELECALLER
        )
        ensure_lead_sources(self.organization)
        self.client = APIClient()
        self.client.credentials(HTTP_X_PROJECT_ID=self.project.code)
        self.client.force_authenticate(self.admin)

    def url(self, suffix):
        return f"/api/v1/organizations/{self.organization.slug}/{suffix.lstrip('/')}"

    def test_nfr_p4_02_phone_normalization_and_weighted_duplicate_scores(self):
        self.assertEqual(normalize_phone("+91 (98765) 43210"), "9876543210")
        same_name = Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Asha", last_name="Sharma",
            phone="9876543210", email="asha@example.test", source="website"
        )
        different_name = Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Neha", last_name="Sharma",
            phone="9876543210", email="neha@example.test", source="website"
        )
        email_partial = Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Ravi", phone="9876543210",
            email="ravi@example.test", source="website"
        )
        self.assertEqual(duplicate_score({"phone": "+91 9876543210", "full_name": "Asha Sharma"}, same_name), 95)
        self.assertEqual(duplicate_score({"phone": "9876543210", "full_name": "Other Name"}, different_name), 90)
        self.assertEqual(duplicate_score({"email": "ravi@example.test", "phone": "3210"}, email_partial), 80)

    def test_api_p4_03_manual_lead_returns_duplicate_warning_before_save(self):
        Lead.objects.create(
            organization=self.organization, project=self.project, first_name="Existing", phone="9999999999",
            email="existing@example.test", source="website"
        )
        response = self.client.post(
            self.url("leads/manual/"),
            {"first_name": "New", "phone": "+91 9999999999", "source": "website"},
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["duplicates"][0]["confidence"], 90)
        self.assertEqual(Lead.objects.filter(phone__contains="9999999999").count(), 1)

    def test_api_p4_04_csv_upload_creates_pending_batch_and_worker_reports_bad_rows(self):
        content = b"first_name,phone,source\nValid,8888888888,website\nInvalid,,website\n"
        upload = SimpleUploadedFile("leads.csv", content, content_type="text/csv")
        with patch("leads.views.enqueue_lead_import") as enqueue:
            response = self.client.post(self.url("leads/import-csv/"), {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 202, response.data)
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        enqueue.assert_called_once_with(batch.id)

        process_import_batch(batch.id)
        batch.refresh_from_db()
        self.assertEqual(batch.imported_rows, 1)
        self.assertEqual(batch.skipped_rows, 1)
        self.assertEqual(batch.status, LeadImportBatch.Status.COMPLETED)
        self.assertEqual(batch.error_report[0]["row"], 3)

    def test_ec_p4_02_meta_redelivery_is_idempotent(self):
        payload = {"external_lead_id": "meta-123", "first_name": "Meta", "phone": "7777777777", "source": "fb"}
        first = self.client.post(self.url("leads/sync/meta/"), payload, format="json")
        second = self.client.post(self.url("leads/sync/meta/"), {**payload, "email": "meta@example.test"}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(Lead.objects.filter(external_source="meta", external_lead_id="meta-123").count(), 1)
        self.assertEqual(Lead.objects.get(external_source="meta", external_lead_id="meta-123").email, "meta@example.test")

    def test_fr_p4_06_only_admin_or_manager_can_import_or_sync(self):
        self.client.force_authenticate(self.telecaller)
        csv_upload = SimpleUploadedFile("leads.csv", b"first_name,phone\nA,6666666666\n", content_type="text/csv")
        self.assertEqual(self.client.post(self.url("leads/import-csv/"), {"file": csv_upload}, format="multipart").status_code, 403)
        self.assertEqual(self.client.post(self.url("leads/sync/google/"), {"external_lead_id": "g-1"}, format="json").status_code, 403)
