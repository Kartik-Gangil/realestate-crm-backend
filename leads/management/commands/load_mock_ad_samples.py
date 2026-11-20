from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import Project
from leads.models import Lead
from organizations.models import Organization
from system_settings.integrations import encrypt_secret
from system_settings.models import IntegrationConfiguration


class Command(BaseCommand):
    help = "Load local-only Meta and Google mock lead samples for a project."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Organization slug.")
        parser.add_argument("--project", required=True, help="Project code.")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("load_mock_ad_samples is available only when DEBUG is on.")

        organization = Organization.objects.filter(slug=options["organization"], is_active=True).first()
        if organization is None:
            raise CommandError("Active organization was not found.")
        project = Project.objects.filter(organization=organization, code=options["project"]).first()
        if project is None:
            raise CommandError("Project was not found in the organization.")

        existing_phone = (
            Lead.objects.filter(organization=organization, project=project)
            .exclude(phone="")
            .order_by("id")
            .values_list("phone", flat=True)
            .first()
            or "9000000001"
        )
        phones = [existing_phone, "9000000002", "9000000003"]
        meta_form_id = f"MOCK-{project.code}-meta_ads"
        google_form_id = f"MOCK-{project.code}-google_ads"
        meta_samples = [
            self._meta_sample(index, project.code, phone, meta_form_id)
            for index, phone in enumerate(phones, start=1)
        ]
        google_samples = [
            self._google_sample(index, project.code, phone, google_form_id)
            for index, phone in enumerate(phones, start=1)
        ]

        definitions = (
            (
                IntegrationConfiguration.Type.META_ADS,
                "Meta Ads Mock Samples",
                meta_form_id,
                meta_samples,
                {"app_secret": "local-meta-test-secret"},
            ),
            (
                IntegrationConfiguration.Type.GOOGLE_ADS,
                "Google Ads Mock Samples",
                google_form_id,
                google_samples,
                {"google_key": "local-google-test-key"},
            ),
        )
        created = 0
        for integration_type, name, form_id, samples, secrets in definitions:
            _, was_created = IntegrationConfiguration.objects.get_or_create(
                organization=organization,
                integration_type=integration_type,
                name=name,
                defaults={
                    "enabled": True,
                    "status": IntegrationConfiguration.Status.CONFIGURED,
                    "configuration": {
                        "form_project_mapping": {form_id: project.id},
                        "mock_payloads": samples,
                    },
                    "encrypted_secrets": encrypt_secret(secrets),
                },
            )
            created += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            f"Mock ad samples ready for {organization.slug}/{project.code}: "
            f"2 integrations, 3 samples each, created={created}."
        ))

    @staticmethod
    def _meta_sample(index, project_code, phone, form_id):
        return {
            "leadgen_id": f"MOCK-META-{project_code}-{index}",
            "form_id": form_id,
            "platform": "facebook",
            "field_data": [
                {"name": "full_name", "values": [f"Meta Mock Lead {index}"]},
                {"name": "phone_number", "values": [phone]},
                {"name": "email", "values": [f"meta-mock-{index}@example.invalid"]},
            ],
        }

    @staticmethod
    def _google_sample(index, project_code, phone, form_id):
        return {
            "lead_id": f"MOCK-GOOGLE-{project_code}-{index}",
            "form_id": form_id,
            "user_column_data": [
                {"column_id": "FULL_NAME", "string_value": f"Google Mock Lead {index}"},
                {"column_id": "PHONE_NUMBER", "string_value": phone},
                {"column_id": "EMAIL", "string_value": f"google-mock-{index}@example.invalid"},
            ],
        }
