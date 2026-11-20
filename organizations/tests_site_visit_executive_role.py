import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from core.tests.factories import make_organization

from .models import OrganizationRole, Permission
from .services import ensure_default_roles


SITE_VISIT_EXECUTIVE_PERMISSION_CODES = {
    "site_visits.view",
    "site_visits.add",
    "site_visits.edit",
    "plots.view",
    "plots.hold",
    "plots.book",
    "leads.view",
}


class SiteVisitExecutiveRoleTemplateTests(TestCase):
    """FR-P7-07, EC-P7-01, Phase 3 v2.9 role-template close-out."""

    def test_new_organization_gets_editable_site_visit_executive_role_with_exact_permissions(self):
        organization = make_organization("site-visit-executive-template")

        role = ensure_default_roles(organization)["site-visit-executive"]

        self.assertEqual(role.name, "Site Visit Executive")
        self.assertFalse(role.is_system)
        self.assertEqual(
            set(role.permissions.values_list("module", "action")),
            {tuple(code.split(".", 1)) for code in SITE_VISIT_EXECUTIVE_PERMISSION_CODES},
        )

    def test_removed_template_permission_survives_role_provisioning(self):
        organization = make_organization("site-visit-executive-permission-persistence")
        role = ensure_default_roles(organization)["site-visit-executive"]
        removed_permission = Permission.objects.get(module="plots", action="view")

        role.permissions.remove(removed_permission)
        ensure_default_roles(organization)

        self.assertFalse(role.permissions.filter(pk=removed_permission.pk).exists())


class SiteVisitExecutiveRoleMigrationTests(TestCase):
    """The close-out data migration is idempotent and organization-scoped."""

    def test_migration_creates_the_role_once_per_organization(self):
        first = make_organization("site-visit-executive-migration-one")
        second = make_organization("site-visit-executive-migration-two")
        existing = OrganizationRole.objects.create(
            organization=first,
            name="Site Visit Executive",
            code="site-visit-executive",
            is_system=False,
        )

        migration = importlib.import_module("organizations.migrations.0026_site_visit_executive_role")
        migration.migrate_site_visit_executive_roles(django_apps, None)
        migration.migrate_site_visit_executive_roles(django_apps, None)

        self.assertEqual(
            OrganizationRole.objects.filter(
                organization_id__in=[first.pk, second.pk],
                code="site-visit-executive",
            ).count(),
            2,
        )
        self.assertEqual(
            OrganizationRole.objects.filter(
                organization=first,
                code="site-visit-executive",
            ).count(),
            1,
        )
        self.assertEqual(
            OrganizationRole.objects.filter(
                organization=second,
                code="site-visit-executive",
            ).count(),
            1,
        )
        self.assertEqual(
            OrganizationRole.objects.get(pk=existing.pk).permissions.count(),
            0,
        )
