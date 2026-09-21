from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0013_project_scope_hr_records"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmembership",
            name="projects",
            field=models.ManyToManyField(
                blank=True,
                help_text="Phase 3 project-scope assignment for this organization user.",
                related_name="assigned_memberships",
                to="organizations.project",
            ),
        ),
    ]
