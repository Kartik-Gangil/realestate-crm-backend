from django.db import migrations

from organizations.permission_catalogue import migrate_unused_permissions


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0023_manager_normal_role"),
        ("system_settings", "0006_alter_auditlog_options"),
    ]

    operations = [
        migrations.RunPython(migrate_unused_permissions, migrations.RunPython.noop),
    ]
