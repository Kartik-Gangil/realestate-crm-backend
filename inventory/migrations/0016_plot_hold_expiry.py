from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0015_require_project_references")]

    operations = [
        migrations.AddField(
            model_name="plothold",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
