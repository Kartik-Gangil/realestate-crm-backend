import hashlib
import hmac
import json
from datetime import datetime, timedelta

from django.core.cache import caches
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from cryptography.fernet import Fernet
from rest_framework.test import APIClient

from core.tests.factories import make_member, make_organization, make_project, project_request_kwargs
from leads.connectors import _mapped_project
from leads.models import Lead
from organizations.models import Permission
from system_settings.integrations import encrypt_secret
from system_settings.models import IntegrationConfiguration


@override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode())
class Phase4Step6ConnectorTests(TestCase):
    """FR-P4-01 / EC-P4-02 / API-P4-01-02 tests."""

    def setUp(self):
        caches["ratelimit"].clear()
        self.organization = make_organization("phase4-step6")
        self.project = make_project(self.organization, "MAIN")
        self.membership = make_member(self.organization, role="manager", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        self.meta_payload = {
            "leadgen_id": "META-1",
            "form_id": "FORM-1",
            "platform": "facebook",
            "field_data": [
                {"name": "full_name", "values": ["Meta Lead"]},
                {"name": "phone_number", "values": ["9876543210"]},
                {"name": "email", "values": ["meta@example.com"]},
            ],
        }
        self.meta_secret = "meta-test-secret"
        self.meta_payload_two = {
            **self.meta_payload,
            "leadgen_id": "META-2",
            "field_data": [
                {"name": "full_name", "values": ["Second Meta Lead"]},
                {"name": "phone_number", "values": ["9876543211"]},
                {"name": "email", "values": ["second-meta@example.com"]},
            ],
        }
        IntegrationConfiguration.objects.create(
            organization=self.organization,
            integration_type="meta_ads",
            name="Meta Ads",
            enabled=True,
            configuration={
                "form_project_mapping": {"FORM-1": self.project.id},
                "mock_payloads": [self.meta_payload, self.meta_payload_two],
            },
            encrypted_secrets=encrypt_secret({"app_secret": self.meta_secret}),
        )

    def meta_signature(self, payload):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return "sha256=" + hmac.new(self.meta_secret.encode(), raw, hashlib.sha256).hexdigest(), raw

    def test_valid_meta_signature_saves_mapped_lead(self):
        signature, raw = self.meta_signature(self.meta_payload)
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/",
            raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        self.assertEqual(response.status_code, 201)
        lead = Lead.objects.get(external_source="meta", external_id="META-1")
        self.assertEqual(lead.project_id, self.project.id)
        self.assertEqual(lead.source, "fb")
        integration = IntegrationConfiguration.objects.get(
            organization=self.organization,
            integration_type="meta_ads",
        )
        self.assertIsNotNone(integration.last_synced_at)

    def test_bad_meta_signature_is_rejected(self):
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/",
            json.dumps(self.meta_payload).encode(),
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=bad",
        )
        self.assertEqual(response.status_code, 403)

    def test_meta_redelivery_is_idempotent(self):
        signature, raw = self.meta_signature(self.meta_payload)
        url = f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/"
        first = self.client.post(url, raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)
        second = self.client.post(url, raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Lead.objects.filter(external_source="meta", external_id="META-1").count(), 1)

    def test_preview_saves_nothing_and_not_connected_returns_409(self):
        url = f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/"
        preview = self.client.post(url, {"preview": True}, format="json", **project_request_kwargs(self.project))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(Lead.objects.count(), 0)
        IntegrationConfiguration.objects.filter(organization=self.organization, integration_type="meta_ads").update(encrypted_secrets="")
        not_connected = self.client.post(url, {}, format="json", **project_request_kwargs(self.project))
        self.assertEqual(not_connected.status_code, 409)

    def test_sync_rejects_request_payloads_without_saving(self):
        url = f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/"
        response = self.client.post(
            url,
            {"payloads": [self.meta_payload]},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Lead.objects.count(), 0)

    def test_preview_uses_stored_leads_and_returns_duplicate_scores(self):
        Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="9876543210",
            source="website",
        )
        url = f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/"
        response = self.client.post(
            url,
            {"preview": True},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([lead["external_id"] for lead in response.data["leads"]], ["META-1", "META-2"])
        self.assertEqual(response.data["leads"][0]["matches"][0]["score"], 90)
        self.assertEqual(Lead.objects.count(), 1)

    def test_sync_imports_only_selected_stored_external_ids(self):
        url = f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/"
        response = self.client.post(
            url,
            {"selected_external_ids": ["META-2"]},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 1)
        self.assertFalse(Lead.objects.filter(external_source="meta", external_id="META-1").exists())
        self.assertTrue(Lead.objects.filter(external_source="meta", external_id="META-2").exists())

    def test_sync_requires_leads_sync(self):
        view_permission = Permission.objects.get(module="leads", action="view")
        project_role = self.membership.project_assignments.get(project=self.project).role
        project_role.permissions.set([view_permission])
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/",
            {},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(response.status_code, 403)

    def test_telecaller_can_create_manual_lead_but_not_import_or_sync(self):
        telecaller = make_member(self.organization, role="telecaller", projects=[self.project])
        client = APIClient()
        client.force_authenticate(telecaller.user)
        manual = client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/manual/",
            {
                "first_name": "Telecaller",
                "phone": "9000000121",
                "source": "website",
            },
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(manual.status_code, 201, manual.data)
        upload = SimpleUploadedFile("leads.csv", b"first_name,phone\nImport,9000000122\n", content_type="text/csv")
        imported = client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/import-csv/",
            {"file": upload},
            format="multipart",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(imported.status_code, 403)
        synced = client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/",
            {},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(synced.status_code, 403)

    def test_google_webhook_rejects_wrong_key_and_accepts_correct_key(self):
        google_secret = "google-test-secret"
        google_payload = {
            "google_key": google_secret,
            "form_id": "GOOGLE-FORM",
            "lead_id": "GOOGLE-1",
            "user_column_data": [
                {"column_id": "FULL_NAME", "string_value": "Google Lead"},
                {"column_id": "PHONE_NUMBER", "string_value": "9876543212"},
                {"column_id": "EMAIL", "string_value": "google@example.com"},
            ],
        }
        IntegrationConfiguration.objects.create(
            organization=self.organization,
            integration_type="google_ads",
            name="Google Ads",
            enabled=True,
            configuration={"form_project_mapping": {"GOOGLE-FORM": self.project.id}},
            encrypted_secrets=encrypt_secret({"google_key": google_secret}),
        )
        url = f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/google/"
        wrong = {**google_payload, "google_key": "wrong"}
        response = self.client.post(url, wrong, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Lead.objects.filter(external_source="google").exists())
        response = self.client.post(url, google_payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(external_source="google", external_id="GOOGLE-1")
        self.assertEqual(lead.source, "google")
        integration = IntegrationConfiguration.objects.get(
            organization=self.organization,
            integration_type="google_ads",
        )
        self.assertIsNotNone(integration.last_synced_at)

    def test_sync_returns_last_synced_at_from_the_integration_api(self):
        synced_at = timezone.now()
        IntegrationConfiguration.objects.filter(
            organization=self.organization,
            integration_type="meta_ads",
        ).update(last_synced_at=synced_at)

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/settings/integrations/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        meta = next(item for item in response.data if item["integration_type"] == "meta_ads")
        returned_at = datetime.fromisoformat(meta["last_synced_at"].replace("Z", "+00:00"))
        self.assertEqual(returned_at, synced_at)

    def test_webhook_rate_limit_is_60_per_address(self):
        signature, raw = self.meta_signature(self.meta_payload)
        url = f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/"
        statuses = [
            self.client.post(url, raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature, REMOTE_ADDR="192.0.2.50").status_code
            for _ in range(61)
        ]
        self.assertEqual(statuses[:60][-1], 200)
        self.assertEqual(statuses[-1], 429)

    def test_mapped_project_accepts_id_digit_string_code_and_returns_none_for_unknown(self):
        integration = IntegrationConfiguration.objects.get(
            organization=self.organization,
            integration_type="meta_ads",
        )
        integration.configuration["form_project_mapping"] = {
            "BY-ID": self.project.id,
            "BY-DIGITS": str(self.project.id),
            "BY-CODE": self.project.code,
            "UNKNOWN": "missing-project",
        }
        integration.save(update_fields=("configuration",))

        self.assertEqual(_mapped_project(self.organization, integration, "BY-ID"), self.project)
        self.assertEqual(_mapped_project(self.organization, integration, "BY-DIGITS"), self.project)
        self.assertEqual(_mapped_project(self.organization, integration, "BY-CODE"), self.project)
        self.assertIsNone(_mapped_project(self.organization, integration, "UNKNOWN"))


@override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode(), DEBUG=True)
class MockStoredSamplesSyncTests(TestCase):
    def setUp(self):
        caches["ratelimit"].clear()
        self.organization = make_organization("phase4-mock-e2e")
        self.project = make_project(self.organization, "MOCK")
        self.membership = make_member(self.organization, role="admin", projects=[self.project])
        self.client = APIClient()
        self.client.force_authenticate(self.membership.user)
        Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="9876543210",
            source=Lead.Source.WEBSITE,
        )
        call_command(
            "load_mock_ad_samples",
            organization=self.organization.slug,
            project=self.project.code,
        )

    def _preview(self, connector):
        return self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/{connector}/",
            {"preview": True},
            format="json",
            **project_request_kwargs(self.project),
        )

    def test_mock_command_samples_preview_three_meta_leads_with_one_duplicate(self):
        response = self._preview("meta")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["leads"]), 3)
        self.assertEqual(
            sum(bool(lead["matches"] and lead["matches"][0].get("score")) for lead in response.data["leads"]),
            1,
        )

    def test_mock_command_samples_preview_three_google_leads_with_one_duplicate(self):
        response = self._preview("google")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["leads"]), 3)
        self.assertEqual(
            sum(bool(lead["matches"] and lead["matches"][0].get("score")) for lead in response.data["leads"]),
            1,
        )

    def test_webhook_form_mapped_by_code_saves_to_the_project(self):
        integration = IntegrationConfiguration.objects.get(
            organization=self.organization,
            integration_type="meta_ads",
        )
        integration.configuration["form_project_mapping"] = {"CODE-FORM": self.project.code}
        integration.save(update_fields=("configuration",))
        payload = {
            "leadgen_id": "CODE-MAPPED-1",
            "form_id": "CODE-FORM",
            "platform": "facebook",
            "field_data": [
                {"name": "full_name", "values": ["Code Mapped"]},
                {"name": "phone_number", "values": ["9000000999"]},
                {"name": "email", "values": ["code-mapped@example.com"]},
            ],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new("local-meta-test-secret".encode(), raw, hashlib.sha256).hexdigest()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/",
            raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Lead.objects.get(external_id="CODE-MAPPED-1").project_id, self.project.id)

    def test_webhook_unknown_form_returns_400(self):
        payload = {
            "leadgen_id": "UNKNOWN-FORM-1",
            "form_id": "UNKNOWN-FORM",
            "platform": "facebook",
            "field_data": [],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new("local-meta-test-secret".encode(), raw, hashlib.sha256).hexdigest()
        response = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/webhooks/meta/",
            raw,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Lead.objects.filter(external_id="UNKNOWN-FORM-1").exists())

    def test_preview_then_imports_two_selected_ids_and_lists_both_for_admin(self):
        preview = self._preview("meta")
        self.assertEqual(preview.status_code, 200, preview.data)
        selected_ids = [
            preview.data["leads"][0]["external_id"],
            preview.data["leads"][1]["external_id"],
        ]

        imported = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/",
            {"selected_external_ids": selected_ids},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(imported.status_code, 200, imported.data)
        self.assertEqual(imported.data["created"], 2)
        self.assertEqual(len(imported.data["leads"]), 2)

        listed = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(listed.status_code, 200, listed.data)
        listed_names = {lead["full_name"] for lead in listed.data["results"]}
        self.assertTrue({"Meta Mock Lead 1", "Meta Mock Lead 2"}.issubset(listed_names))

        repeated = self.client.post(
            f"/api/v1/organizations/{self.organization.slug}/leads/sync/meta/",
            {"selected_external_ids": selected_ids},
            format="json",
            **project_request_kwargs(self.project),
        )
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["created"], 0)
        self.assertEqual(sum(bool(lead.get("idempotent")) for lead in repeated.data["leads"]), 2)

    def test_admin_lead_list_orders_newest_lead_first(self):
        older = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Older",
            phone="9000000991",
            source=Lead.Source.WEBSITE,
        )
        newer = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Newest",
            phone="9000000992",
            source="google",
        )
        Lead.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        Lead.objects.filter(pk=newer.pk).update(created_at=timezone.now())

        response = self.client.get(
            f"/api/v1/organizations/{self.organization.slug}/leads/",
            **project_request_kwargs(self.project),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["id"], newer.id)
