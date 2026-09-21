import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0025_dynamic_site_visit_outcome"),
        ("organizations", "0014_organizationmembership_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="external_lead_id",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="lead",
            name="external_source",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddConstraint(
            model_name="lead",
            constraint=models.UniqueConstraint(
                condition=~models.Q(external_source="") & ~models.Q(external_lead_id=""),
                fields=("organization", "external_source", "external_lead_id"),
                name="lead_external_identity_unique",
            ),
        ),
        migrations.CreateModel(
            name="LeadImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file_name", models.CharField(max_length=255)),
                ("raw_content", models.TextField()),
                ("field_mapping", models.JSONField(blank=True, default=dict)),
                ("total_rows", models.PositiveIntegerField(default=0)),
                ("imported_rows", models.PositiveIntegerField(default=0)),
                ("skipped_rows", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=16)),
                ("error_report", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_import_batches", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lead_import_batches", to="organizations.organization")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["organization", "status", "created_at"], name="leads_leadi_organiz_408d92_idx")],
            },
        ),
    ]
