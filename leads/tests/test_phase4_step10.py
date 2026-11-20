import hashlib
import hmac
import importlib
import json

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.models import Lead, LeadImportBatch
from organizations.models import OrganizationMembership
from system_settings.integrations import encrypt_secret
from system_settings.models import IntegrationConfiguration, MasterData


@override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode(), DEBUG=True)
class IngestionLeadStatusTests(TestCase):
    """DM-P4-01/FR-P4-01/FR-P4-03/FR-P4-04: new leads start at the new stage."""

    def setUp(self):
        self.organization = make_organization("phase4-step10")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role=OrganizationMembership.Role.ADMIN, projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        self.new_stage = MasterData.objects.get(project=self.project, category__code="lead_stage", code="new")

    def test_synced_lead_gets_new_stage(self):
        call_command("load_mock_ad_samples", organization=self.organization.slug, project=self.project.code)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/",
            {"selected_external_ids": [f"MOCK-META-{self.project.code}-1"]},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200, response.data)
        lead = Lead.objects.get(external_source="meta")
        self.assertEqual(lead.status_id, self.new_stage.id)

    def test_webhook_lead_gets_new_stage(self):
        secret = "meta-status-secret"
        IntegrationConfiguration.objects.create(
            organization=self.organization,
            integration_type=IntegrationConfiguration.Type.META_ADS,
            name="Meta Ads",
            enabled=True,
            configuration={"form_project_mapping": {"FORM-1": self.project.id}},
            encrypted_secrets=encrypt_secret({"app_secret": secret}),
        )
        payload = {
            "leadgen_id": "META-STATUS-1",
            "form_id": "FORM-1",
            "platform": "facebook",
            "field_data": [
                {"name": "full_name", "values": ["Webhook Status"]},
                {"name": "phone_number", "values": ["9000000101"]},
            ],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/",
            raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(external_source="meta", external_id="META-STATUS-1")
        self.assertEqual(lead.status_id, self.new_stage.id)

    def test_csv_imported_lead_gets_new_stage(self):
        upload = SimpleUploadedFile(
            "status.csv",
            b"first_name,phone\nCSV Status,9000000102\n",
            content_type="text/csv",
        )
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-csv/",
            {"file": upload},
            format="multipart",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 202, response.data)
        call_command("run_worker", "--once")
        lead = Lead.objects.get(phone="+919000000102")
        self.assertEqual(lead.status_id, self.new_stage.id)


class ExactCsvDuplicateImportTests(TestCase):
    """FR-P4-03/FR-P4-04: the exact owner CSV skips the existing normalized phone."""

    def setUp(self):
        self.organization = make_organization("phase4-step10-csv")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role=OrganizationMembership.Role.ADMIN, projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing Copy",
            phone="+919876500001",
            source=Lead.Source.WEBSITE,
        )

    def test_exact_owner_csv_imports_one_and_skips_two_when_duplicates_are_disabled(self):
        content = (
            "first_name,last_name,phone,email\n"
            "Ravi,Kumar,9876500002,ravi.test@example.com\n"
            "Bad,Phone,12345,bad.test@example.com\n"
            "Copy,Lead,9876500001,copy.test@example.com\n"
        ).encode()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-csv/",
            {"file": SimpleUploadedFile("owner.csv", content, content_type="text/csv")},
            format="multipart",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 202, response.data)
        call_command("run_worker", "--once")
        batch = LeadImportBatch.objects.get(pk=response.data["batch_id"])
        self.assertEqual(batch.import_duplicates, False)
        self.assertEqual(batch.imported_rows, 1)
        self.assertEqual(batch.skipped_rows, 2)
        self.assertEqual(Lead.objects.filter(project=self.project, phone="+919876500001").count(), 1)
        self.assertTrue(Lead.objects.filter(project=self.project, first_name="Ravi").exists())
        self.assertFalse(Lead.objects.filter(project=self.project, first_name="Copy").exists())


class LeadStatusBackfillMigrationTests(TransactionTestCase):
    """DM-P4-01/GNFR-09: migration repairs null statuses with one bulk audit row."""

    migrate_from = ("leads", "0027_alter_lead_source")
    migrate_to = ("leads", "0028_backfill_missing_lead_status")

    def test_0028_backfills_new_and_latest_follow_up_status_on_sample_data(self):
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state([self.migrate_from])
        apps = state.apps
        Organization = apps.get_model("organizations", "Organization")
        Project = apps.get_model("inventory", "Project")
        Lead = apps.get_model("leads", "Lead")
        FollowUpCall = apps.get_model("leads", "FollowUpCall")
        MasterData = apps.get_model("system_settings", "MasterData")
        MasterDataCategory = apps.get_model("system_settings", "MasterDataCategory")
        AuditLog = apps.get_model("system_settings", "AuditLog")

        organization = Organization.objects.create(name="Migration sample", slug="migration-sample")
        project = Project.objects.create(organization=organization, name="Migration project", code="MIG")
        stage_category, _ = MasterDataCategory.objects.get_or_create(
            code="lead_stage", defaults={"name": "Lead stage", "is_system": True}
        )
        new_stage = MasterData.objects.create(
            organization=organization, project=project, category=stage_category, code="new", name="New", is_active=True,
        )
        contacted_stage = MasterData.objects.create(
            organization=organization, project=project, category=stage_category, code="contacted", name="Contacted", is_active=True,
        )
        Lead.objects.bulk_create([
            Lead(organization=organization, project=project, first_name="No Follow Up", phone="+919000000201", source="website"),
            Lead(organization=organization, project=project, first_name="Has Follow Up", phone="+919000000202", source="website"),
        ])
        with_follow_up = Lead.objects.get(first_name="Has Follow Up")
        FollowUpCall.objects.create(organization=organization, lead=with_follow_up, status="contacted")

        importlib.import_module("leads.migrations.0028_backfill_missing_lead_status").backfill_missing_lead_status(apps, None)
        self.assertEqual(Lead.objects.get(first_name="No Follow Up").status_id, new_stage.id)
        self.assertEqual(Lead.objects.get(first_name="Has Follow Up").status_id, contacted_stage.id)
        audit_rows = AuditLog.objects.filter(route="migration:leads.0028_backfill_missing_lead_status")
        self.assertEqual(audit_rows.count(), 1)
        audit = audit_rows.get()
        self.assertEqual(audit.action, "bulk_update")
        self.assertEqual(audit.details["changed_values"]["fields"], ["status"])
        self.assertEqual(len(audit.details["record_ids"]), 2)

