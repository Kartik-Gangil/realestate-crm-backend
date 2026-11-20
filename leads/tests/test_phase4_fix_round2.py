import importlib
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase

from core.tests.factories import make_organization, make_project
from leads.codes import allocate_lead_codes
from leads.models import Lead, LeadCodeSequence
from system_settings.models import AuditLog


class Phase4LeadCodeTests(TestCase):
    def setUp(self):
        self.organization = make_organization("phase4-fix-round2-codes")
        self.project = make_project(self.organization, "CODES")

    def test_two_leads_created_in_one_allocation_have_different_project_codes_dm_p4_01(self):
        first, second = allocate_lead_codes(self.project, 2)
        self.assertEqual(first, "CODES-L-000001")
        self.assertEqual(second, "CODES-L-000002")
        self.assertEqual(allocate_lead_codes(self.project, 1), ["CODES-L-000003"])

    def test_code_allocator_uses_project_row_lock_on_sqlite(self):
        with patch("leads.codes.Project.objects.select_for_update", wraps=self.project.__class__.objects.select_for_update) as locked:
            allocate_lead_codes(self.project, 1)
        locked.assert_called_once_with()


class Phase4LeadFieldsMigrationTests(TestCase):
    def test_0024_data_migration_backfills_sample_legacy_lead(self):
        organization = make_organization("phase4-fix-round2-migration")
        project = make_project(organization, "MIGRATE")
        gap = Lead.objects.create(
            organization=organization,
            project=project,
            first_name="Gap",
            phone="9876543211",
            source="website",
        )
        lead = Lead.objects.create(
            organization=organization,
            project=project,
            first_name="Legacy",
            phone="9876543210",
            source="website",
        )
        gap.delete()
        Lead.objects.filter(pk=lead.pk).update(
            lead_code="",
            source="facebook",
            source_item=None,
            status=None,
            phone="09876543210",
        )
        migration = importlib.import_module("leads.migrations.0024_phase4_lead_fields")

        migration.backfill_leads(apps, None)
        renumber = importlib.import_module("leads.migrations.0029_renumber_project_lead_codes")
        renumber.renumber_project_lead_codes(apps, None)

        lead.refresh_from_db()
        self.assertEqual(lead.lead_code, "MIGRATE-L-000001")
        self.assertEqual(LeadCodeSequence.objects.get(project=project).next_number, 2)
        self.assertEqual(lead.phone, "+919876543210")
        self.assertEqual(lead.source_item.code, "fb")
        self.assertEqual(lead.status.code, "new")
        self.assertTrue(
            AuditLog.objects.filter(
                module="leads",
                action="phase4_migration_backfill",
                target_type="Lead",
                target_id=str(lead.pk),
            ).exists()
        )


class ProjectLeadCodeRenumberMigrationTests(TestCase):
    def test_renumbers_each_project_in_creation_order_and_audits_one_bulk_row_per_project(self):
        organization = make_organization("phase4-fix-round10-code-migration")
        first_project = make_project(organization, "FIRST")
        second_project = make_project(organization, "SECOND")

        first_old = Lead.objects.create(
            organization=organization,
            project=first_project,
            first_name="First old",
            phone="9876543201",
            source="website",
        )
        second_first = Lead.objects.create(
            organization=organization,
            project=second_project,
            first_name="Second first",
            phone="9876543202",
            source="website",
        )
        first_newest = Lead.objects.create(
            organization=organization,
            project=first_project,
            first_name="First newest",
            phone="9876543203",
            source="website",
        )
        second_newest = Lead.objects.create(
            organization=organization,
            project=second_project,
            first_name="Second newest",
            phone="9876543204",
            source="website",
        )
        gap = Lead.objects.create(
            organization=organization,
            project=first_project,
            first_name="Deleted gap",
            phone="9876543205",
            source="website",
        )
        gap.delete()

        old_codes = {
            first_old.pk: "FIRST-L-000041",
            first_newest.pk: "FIRST-L-000099",
            second_first.pk: "SECOND-L-000017",
            second_newest.pk: "SECOND-L-000031",
        }
        Lead.objects.filter(pk__in=old_codes).update(lead_code="")
        for lead_id, old_code in old_codes.items():
            Lead.objects.filter(pk=lead_id).update(lead_code=old_code)
        LeadCodeSequence.objects.update_or_create(project=first_project, defaults={"next_number": 900})
        LeadCodeSequence.objects.update_or_create(project=second_project, defaults={"next_number": 700})

        migration = importlib.import_module("leads.migrations.0029_renumber_project_lead_codes")
        migration.renumber_project_lead_codes(apps, None)

        first_old.refresh_from_db()
        first_newest.refresh_from_db()
        second_first.refresh_from_db()
        second_newest.refresh_from_db()
        self.assertEqual(first_old.lead_code, "FIRST-L-000001")
        self.assertEqual(first_newest.lead_code, "FIRST-L-000002")
        self.assertEqual(second_first.lead_code, "SECOND-L-000001")
        self.assertEqual(second_newest.lead_code, "SECOND-L-000002")
        self.assertEqual(LeadCodeSequence.objects.get(project=first_project).next_number, 3)
        self.assertEqual(LeadCodeSequence.objects.get(project=second_project).next_number, 3)

        first_audit = AuditLog.objects.get(
            route="migration:leads.0029_renumber_project_lead_codes",
            project=first_project,
        )
        second_audit = AuditLog.objects.get(
            route="migration:leads.0029_renumber_project_lead_codes",
            project=second_project,
        )
        self.assertEqual(
            first_audit.details,
            {
                "lead_codes": {
                    str(first_old.pk): {"old": "FIRST-L-000041", "new": "FIRST-L-000001"},
                    str(first_newest.pk): {"old": "FIRST-L-000099", "new": "FIRST-L-000002"},
                }
            },
        )
        self.assertEqual(
            second_audit.details,
            {
                "lead_codes": {
                    str(second_first.pk): {"old": "SECOND-L-000017", "new": "SECOND-L-000001"},
                    str(second_newest.pk): {"old": "SECOND-L-000031", "new": "SECOND-L-000002"},
                }
            },
        )
        self.assertEqual(
            AuditLog.objects.filter(route="migration:leads.0029_renumber_project_lead_codes").count(),
            2,
        )

        next_lead = Lead.objects.create(
            organization=organization,
            project=first_project,
            first_name="Next",
            phone="9876543206",
            source="website",
        )
        self.assertEqual(next_lead.lead_code, "FIRST-L-000003")
