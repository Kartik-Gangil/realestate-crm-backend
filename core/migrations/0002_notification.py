from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_taskrecord_and_cache"),
        ("inventory", "0015_require_project_references"),
        ("organizations", "0018_backfill_project_assignments"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(max_length=100)),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField()),
                ("related_object_type", models.CharField(blank=True, max_length=150)),
                ("related_object_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("read", "Read")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="organizations.organization")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notifications", to="inventory.project")),
                ("recipient_membership", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="organizations.organizationmembership")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["recipient_membership", "status", "-created_at"], name="core_notifi_recipie_5d3d83_idx"),
                    models.Index(fields=["organization", "project", "-created_at"], name="core_notifi_organiz_eb1837_idx"),
                ],
            },
        ),
    ]
