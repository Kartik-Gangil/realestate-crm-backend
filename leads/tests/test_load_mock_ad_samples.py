from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from cryptography.fernet import Fernet

from core.tests.factories import make_organization, make_project
from leads.models import Lead
from system_settings.integrations import decrypt_secret
from system_settings.models import IntegrationConfiguration


@override_settings(INTEGRATION_ENCRYPTION_KEY=Fernet.generate_key().decode(), DEBUG=True)
class LoadMockAdSamplesCommandTests(TestCase):
    def setUp(self):
        self.organization = make_organization("mock-samples")
        self.project = make_project(self.organization, "MOCK")
        existing = Lead.objects.create(
            organization=self.organization,
            project=self.project,
            first_name="Existing",
            phone="9876543210",
            source=Lead.Source.WEBSITE,
        )
        self.existing_phone = existing.phone

    def test_command_creates_both_integrations_with_three_mapped_samples(self):
        call_command("load_mock_ad_samples", organization=self.organization.slug, project=self.project.code)

        integrations = IntegrationConfiguration.objects.filter(organization=self.organization)
        self.assertSetEqual(set(integrations.values_list("integration_type", flat=True)), {"meta_ads", "google_ads"})
        for integration in integrations:
            self.assertTrue(integration.enabled)
            self.assertEqual(integration.configuration["form_project_mapping"], {f"MOCK-{self.project.code}-{integration.integration_type}": self.project.id})
            samples = integration.configuration["mock_payloads"]
            self.assertEqual(len(samples), 3)
            self.assertEqual(samples[0]["field_data"][1]["values"][0] if integration.integration_type == "meta_ads" else samples[0]["user_column_data"][1]["string_value"], self.existing_phone)
            self.assertTrue(decrypt_secret(integration.encrypted_secrets))

    def test_command_is_idempotent(self):
        call_command("load_mock_ad_samples", organization=self.organization.slug, project=self.project.code)
        first = list(IntegrationConfiguration.objects.filter(organization=self.organization).values_list("integration_type", "name", "enabled", "configuration", "encrypted_secrets"))
        call_command("load_mock_ad_samples", organization=self.organization.slug, project=self.project.code)
        second = list(IntegrationConfiguration.objects.filter(organization=self.organization).values_list("integration_type", "name", "enabled", "configuration", "encrypted_secrets"))
        self.assertEqual(first, second)
        self.assertEqual(IntegrationConfiguration.objects.filter(organization=self.organization).count(), 2)

    @override_settings(DEBUG=False)
    def test_command_refuses_to_run_when_debug_is_off(self):
        with self.assertRaises(CommandError):
            call_command("load_mock_ad_samples", organization=self.organization.slug, project=self.project.code)
        self.assertFalse(IntegrationConfiguration.objects.filter(organization=self.organization).exists())
