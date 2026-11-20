import csv
import io
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import TaskRecord
from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead, LeadImportBatch


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}})
class Phase4Step5ImportTests(TestCase):
    """FR-P4-03 / EC-P4-01 / NFR-P4-01 / DM-P4-02 / API-P4-04 tests."""

    def setUp(self):
        self.organization = make_organization("phase4-step5")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        self.url = f"/api/v1/organizations/{self.organization.slug}/leads/import-csv/"
        self.kwargs = project_request_kwargs(self.project)

    def upload(self, rows, name="leads.csv", import_duplicates=False):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["first_name", "last_name", "phone", "email"])
        writer.writeheader()
        writer.writerows(rows)
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile(name, output.getvalue().encode(), content_type="text/csv"), "import_duplicates": import_duplicates},
            format="multipart",
            **self.kwargs,
        )

    def test_request_returns_202_without_saving_rows_and_worker_processes_500_row_chunks(self):
        rows = [{"first_name": f"Lead{index}", "last_name": "Import", "phone": f"987{index:07d}"[-10:], "email": ""} for index in range(10000)]
        response = self.upload(rows)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(Lead.objects.count(), 0)
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        self.assertEqual(TaskRecord.objects.filter(task_path__contains="process_lead_import").count(), 1)
        with self.settings(TASK_RETRY_DELAY_SECONDS=0):
            call_command("run_worker", "--once")
        batch.refresh_from_db()
        self.assertEqual(batch.status, LeadImportBatch.Status.COMPLETED)
        self.assertEqual(batch.total_rows, 10000)
        self.assertEqual(batch.imported_rows, 10000)
        self.assertEqual(batch.current_chunk, 20)

    def test_malformed_rows_are_skipped_and_error_report_is_available(self):
        response = self.upload([
            {"first_name": "Valid", "last_name": "Lead", "phone": "9876543210", "email": ""},
            {"first_name": "Invalid", "last_name": "Lead", "phone": "bad", "email": ""},
        ])
        self.assertEqual(response.status_code, 202)
        call_command("run_worker", "--once")
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        self.assertEqual(batch.imported_rows, 1)
        report = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-batches/{batch.id}/error-report/",
            **self.kwargs,
        )
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Phone number cannot be normalized", b"".join(report.streaming_content))

    def test_worker_resume_after_mid_batch_stop_does_not_import_a_chunk_twice(self):
        rows = [
            {"first_name": f"Lead{index}", "last_name": "Resume", "phone": f"900000{index + 2000:04d}", "email": ""}
            for index in range(1000)
        ]
        response = self.upload(rows)
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        original_bulk_create = Lead.objects.bulk_create
        calls = {"count": 0}

        def stop_after_first_chunk(leads, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated worker stop")
            return original_bulk_create(leads, *args, **kwargs)

        with patch("leads.tasks.Lead.objects.bulk_create", side_effect=stop_after_first_chunk):
            with self.settings(TASK_RETRY_DELAY_SECONDS=0):
                call_command("run_worker", "--once")
        batch.refresh_from_db()
        self.assertEqual(batch.current_chunk, 1)
        self.assertEqual(Lead.objects.filter(project=self.project).count(), 500)
        with self.settings(TASK_RETRY_DELAY_SECONDS=0):
            call_command("run_worker", "--once")
        batch.refresh_from_db()
        self.assertEqual(batch.status, LeadImportBatch.Status.COMPLETED)
        self.assertEqual(batch.imported_rows, 1000)
        self.assertEqual(Lead.objects.filter(project=self.project).count(), 1000)
        self.assertEqual(Lead.objects.filter(project=self.project).values("phone").distinct().count(), 1000)

    def test_non_import_user_cannot_read_another_users_batch_progress_or_error_report(self):
        response = self.upload([
            {"first_name": "Invalid", "last_name": "Lead", "phone": "bad", "email": ""},
        ])
        batch_id = response.data["batch_id"]
        other = make_member(self.organization, role="telecaller", projects=[self.project])
        self.client.force_authenticate(other.user)
        progress = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-batches/{batch_id}/",
            **self.kwargs,
        )
        report = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-batches/{batch_id}/error-report/",
            **self.kwargs,
        )
        self.assertEqual(progress.status_code, 403)
        self.assertEqual(report.status_code, 403)

    def test_duplicates_are_skipped_unless_import_duplicates_is_enabled(self):
        Lead.objects.create(organization=self.organization, project=self.project, first_name="Existing", phone="9876543210", source="website")
        response = self.upload([{"first_name": "Duplicate", "last_name": "Lead", "phone": "9876543210", "email": ""}])
        self.assertEqual(response.status_code, 202)
        call_command("run_worker", "--once")
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        self.assertEqual(batch.imported_rows, 0)
        self.assertEqual(batch.skipped_rows, 1)

        response = self.upload([{"first_name": "Duplicate", "last_name": "Lead", "phone": "9876543210", "email": ""}], import_duplicates=True)
        call_command("run_worker", "--once")
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        self.assertEqual(batch.imported_rows, 1)

    def test_file_over_5mb_is_rejected(self):
        response = self.client.post(
            self.url,
            {"file": SimpleUploadedFile("large.csv", b"x" * (5 * 1024 * 1024 + 1), content_type="text/csv")},
            format="multipart",
            **self.kwargs,
        )
        self.assertEqual(response.status_code, 400)
