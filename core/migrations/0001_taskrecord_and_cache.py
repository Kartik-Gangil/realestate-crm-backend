from django.core.management import call_command
from django.db import migrations, models
import uuid


def create_cache_table(apps, schema_editor):
    call_command(
        "createcachetable",
        "crm_cache",
        database=schema_editor.connection.alias,
        verbosity=0,
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="TaskRecord",
            fields=[
                ("id", models.CharField(default=uuid.uuid4, max_length=64, primary_key=True, serialize=False)),
                ("task_path", models.CharField(max_length=512)),
                ("queue_name", models.CharField(default="default", max_length=100)),
                ("priority", models.SmallIntegerField(default=0)),
                ("args", models.JSONField(default=list)),
                ("kwargs", models.JSONField(default=dict)),
                ("run_after", models.DateTimeField()),
                ("enqueued_at", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempted_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("READY", "Ready"), ("RUNNING", "Running"), ("FAILED", "Failed"), ("SUCCESSFUL", "Successful")], default="READY", max_length=12)),
                ("worker_ids", models.JSONField(default=list)),
                ("return_value", models.JSONField(blank=True, null=True)),
                ("error_type", models.CharField(blank=True, max_length=512, null=True)),
            ],
            options={
                "indexes": [models.Index(fields=["status", "run_after", "priority", "enqueued_at"], name="core_taskre_status_a0de84_idx")],
            },
        ),
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
