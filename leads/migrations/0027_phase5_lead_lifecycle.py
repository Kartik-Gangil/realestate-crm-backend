import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0026_phase4_lead_acquisition"),
        ("organizations", "0014_organizationmembership_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="lead", name="city", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="lead", name="score", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="lead", name="status", field=models.CharField(default="new", max_length=64)),
        migrations.CreateModel(
            name="LeadAssignmentHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignments_made", to=settings.AUTH_USER_MODEL)),
                ("assigned_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignments_from", to="organizations.organizationmembership")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignments_to", to="organizations.organizationmembership")),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assignment_history", to="leads.lead")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="LeadStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_status", models.CharField(blank=True, default="", max_length=64)),
                ("new_status", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_status_changes", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="status_history", to="leads.lead")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="LeadTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tag_name", models.CharField(max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tags", to="leads.lead")),
            ],
            options={
                "ordering": ["tag_name", "id"],
                "constraints": [models.UniqueConstraint(fields=("lead", "tag_name"), name="lead_tag_unique")],
            },
        ),
    ]
