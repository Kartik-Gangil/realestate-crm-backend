from django.db import transaction


STANDARD_PERMISSION_ACTIONS = ("view", "add", "edit", "delete", "export", "approve")

# Every named action retained in the catalogue has one explicit requirement
# owner. This is intentionally centralized so a new action cannot be added to
# the database without either a code/requirement decision or a cleanup decision.
ALLOWED_NAMED_PERMISSION_REQUIREMENTS = {
    "documents.view_team": "FR-P3-07",
    "employees.view_team": "FR-P3-07",
    "expenses.edit_own": "FR-P16-06",
    "expenses.manage_categories": "FR-P16-01",
    "expenses.mark_paid": "FR-P16-06",
    "expenses.process_payment": "FR-P16-06",
    "expenses.process_reimbursement": "FR-P16-06",
    "expenses.reject": "FR-P16-02",
    "expenses.submit": "FR-P16-02",
    "expenses.view_own": "FR-P16-06",
    "expenses.view_team": "FR-P16-06",
    "leads.view_team": "FR-P3-07",
    "leads.import": "FR-P4-03",
    "leads.sync": "FR-P4-01",
    "payments.adjust": "FR-P11-06",
    "payments.receipt": "FR-P11-07",
    "payments.refund": "FR-P11-06",
    "plots.view_team": "FR-P3-07",
    "plots.hold": "FR-P8-07",
    "plots.book": "FR-P9-09",
    "registry.cancel": "FR-P13-01",
    "registry.charges": "FR-P13-02",
    "registry.documents": "FR-P13-03",
    "registry.status": "FR-P13-05",
    "site_visits.view_team": "FR-P3-07",
    "telecalling.view_team": "FR-P3-07",
}

# Owner-approved dry-run delete list. These are non-standard actions only;
# standard actions remain in every module and loans.* remains hidden under G-5.
UNUSED_PERMISSION_CODES = ("expenses.reports",)

# These are deliberately retained for a separate owner decision. They are not
# part of the delete migration and have no requirement mapping today.
OWNER_REVIEW_EXTRA_PERMISSION_CODES = ("payments.cancel", "registry.reports")


def migrate_unused_permissions(apps, schema_editor):
    Permission = apps.get_model("organizations", "Permission")
    OrganizationRole = apps.get_model("organizations", "OrganizationRole")
    AuditLog = apps.get_model("system_settings", "AuditLog")

    with transaction.atomic():
        removable = list(
            Permission.objects.filter(
                module__in=[code.split(".", 1)[0] for code in UNUSED_PERMISSION_CODES],
                action__in=[code.split(".", 1)[1] for code in UNUSED_PERMISSION_CODES],
            )
        )
        if not removable:
            return

        removable_ids = [permission.pk for permission in removable]
        removable_codes = sorted(
            f"{permission.module}.{permission.action}" for permission in removable
        )
        affected_roles = list(
            OrganizationRole.objects.filter(permissions__in=removable_ids)
            .distinct()
            .prefetch_related("permissions")
        )

        for role in affected_roles:
            before = sorted(
                f"{permission.module}.{permission.action}"
                for permission in role.permissions.all()
            )
            role.permissions.remove(*removable_ids)
            after = sorted(
                f"{permission.module}.{permission.action}"
                for permission in role.permissions.all()
            )
            AuditLog.objects.create(
                organization_id=role.organization_id,
                project_id=None,
                user_id=None,
                module="organizations",
                action="unused_permissions_removed",
                method="COMMAND",
                route="command:migrate",
                details={
                    "role_code": role.code,
                    "removed_permissions": removable_codes,
                },
                payload_before={"permissions": before},
                payload_after={"permissions": after},
                target_type="OrganizationRole",
                target_id=str(role.pk),
            )

        Permission.objects.filter(pk__in=removable_ids).delete()
