from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0012_registrydocument"),
        ("organizations", "0015_complete_permission_catalogue"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="assigned_memberships",
            field=models.ManyToManyField(
                blank=True,
                related_name="assigned_projects",
                to="organizations.organizationmembership",
            ),
        ),
    ]
