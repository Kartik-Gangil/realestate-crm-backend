from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("leads", "0029_renumber_project_lead_codes")]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="lifecycle_status",
            field=models.CharField(default="new", max_length=32),
        ),
        migrations.CreateModel(
            name="LeadAssignmentHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignment_actions", to=settings.AUTH_USER_MODEL)),
                ("assigned_from", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignments_from", to="organizations.organizationmembership")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_assignments_to", to="organizations.organizationmembership")),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignment_history", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lead_assignment_history", to="organizations.organization")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="LeadStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_status", models.CharField(max_length=32)),
                ("new_status", models.CharField(max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_status_actions", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lead_status_history", to="organizations.organization")),
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
            options={"ordering": ["tag_name", "id"]},
        ),
        migrations.AddConstraint(
            model_name="leadtag",
            constraint=models.UniqueConstraint(fields=("lead", "tag_name"), name="unique_lead_tag"),
        ),
    ]
