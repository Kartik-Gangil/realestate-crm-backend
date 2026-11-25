import re

from django.db import migrations, models
from django.db.models import Q


def normalize_mobile(value):
    compact = re.sub(r"\D", "", (value or "").strip())
    if not compact:
        return ""
    if compact.startswith("0") and len(compact) == 11:
        compact = compact[1:]
    elif compact.startswith("91") and len(compact) == 12:
        compact = compact[2:]
    if len(compact) != 10 or compact[0] not in "6789":
        return ""
    return f"+91{compact}"


def normalize_existing_mobile_numbers(apps, schema_editor):
    Membership = apps.get_model("organizations", "OrganizationMembership")
    database = schema_editor.connection.alias
    seen = set()
    for membership in Membership.objects.using(database).exclude(mobile_number="").order_by("organization_id", "pk"):
        normalized = normalize_mobile(membership.mobile_number)
        key = (membership.organization_id, normalized)
        if not normalized or key in seen:
            normalized = ""
        else:
            seen.add(key)
        if membership.mobile_number != normalized:
            Membership.objects.using(database).filter(pk=membership.pk).update(mobile_number=normalized)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0032_uat_bug_02_users_manage")]

    operations = [
        migrations.RunPython(normalize_existing_mobile_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.UniqueConstraint(
                condition=~Q(mobile_number=""),
                fields=("organization", "mobile_number"),
                name="unique_organization_mobile_number",
            ),
        ),
    ]
