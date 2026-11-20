from django.apps import apps as django_apps
from django.test import TestCase

from system_settings.models import AuditLog

from .models import OrganizationRole, Permission
from .permission_catalogue import (
    ALLOWED_NAMED_PERMISSION_REQUIREMENTS,
    OWNER_REVIEW_EXTRA_PERMISSION_CODES,
    STANDARD_PERMISSION_ACTIONS,
    UNUSED_PERMISSION_CODES,
    migrate_unused_permissions,
)


class UnusedPermissionMigrationTests(TestCase):
    """DM-P3-02 / GNFR-07: remove only the owner-approved unused action."""

    def setUp(self):
        self.organization = self._make_organization()

    def _make_organization(self):
        from .models import Organization

        return Organization.objects.create(name="Permission Cleanup", slug="permission-cleanup")

    def _permission(self, code):
        module, action = code.split(".", 1)
        permission, _ = Permission.objects.get_or_create(
            module=module,
            action=action,
            defaults={"name": f"{action.title()} {module}"},
        )
        return permission

    def test_migration_deletes_exactly_the_dry_run_list_and_audits_each_affected_role(self):
        removable = self._permission("expenses.reports")
        retained = self._permission("expenses.view")
        untouched_extra = self._permission("payments.cancel")
        role_one = OrganizationRole.objects.create(
            organization=self.organization,
            name="Reports holder",
            code="reports-holder",
        )
        role_two = OrganizationRole.objects.create(
            organization=self.organization,
            name="Second reports holder",
            code="second-reports-holder",
        )
        role_three = OrganizationRole.objects.create(
            organization=self.organization,
            name="No reports",
            code="no-reports",
        )
        role_one.permissions.add(removable, retained, untouched_extra)
        role_two.permissions.add(removable, retained)
        role_three.permissions.add(retained, untouched_extra)
        before = set(Permission.objects.values_list("module", "action"))

        migrate_unused_permissions(django_apps, None)

        after = set(Permission.objects.values_list("module", "action"))
        self.assertEqual(
            before - after,
            {("expenses", "reports")},
        )
        self.assertFalse(Permission.objects.filter(pk=removable.pk).exists())
        self.assertTrue(Permission.objects.filter(pk=untouched_extra.pk).exists())
        self.assertEqual(
            {f"{module}.{action}" for module, action in OrganizationRole.objects.get(pk=role_one.pk).permissions.values_list("module", "action")},
            {"expenses.view", "payments.cancel"},
        )
        self.assertEqual(
            {f"{module}.{action}" for module, action in OrganizationRole.objects.get(pk=role_two.pk).permissions.values_list("module", "action")},
            {"expenses.view"},
        )
        self.assertEqual(
            {f"{module}.{action}" for module, action in OrganizationRole.objects.get(pk=role_three.pk).permissions.values_list("module", "action")},
            {"expenses.view", "payments.cancel"},
        )

        audits = AuditLog.objects.filter(
            route="command:migrate",
            action="unused_permissions_removed",
        )
        self.assertEqual(audits.count(), 2)
        self.assertEqual(
            set(audits.values_list("target_id", flat=True)),
            {str(role_one.pk), str(role_two.pk)},
        )
        self.assertTrue(all(row.user_id is None for row in audits))
        self.assertTrue(all(row.details["removed_permissions"] == ["expenses.reports"] for row in audits))

    def test_every_named_permission_is_requirement_traceable_or_explicitly_owner_reviewed(self):
        named_codes = {
            permission.code
            for permission in Permission.objects.exclude(action__in=STANDARD_PERMISSION_ACTIONS)
            if permission.module != "loans"
        }
        traceable = set(ALLOWED_NAMED_PERMISSION_REQUIREMENTS)
        traceable.update(UNUSED_PERMISSION_CODES)
        traceable.update(OWNER_REVIEW_EXTRA_PERMISSION_CODES)
        self.assertEqual(named_codes - traceable, set())
        self.assertEqual(UNUSED_PERMISSION_CODES, ("expenses.reports",))
        self.assertEqual(
            OWNER_REVIEW_EXTRA_PERMISSION_CODES,
            ("payments.cancel", "registry.reports"),
        )
