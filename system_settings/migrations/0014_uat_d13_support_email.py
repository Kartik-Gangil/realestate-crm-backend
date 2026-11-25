from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0013_group_e_leave_parameters")]

    operations = [
        migrations.AddField(
            model_name="organizationsettings",
            name="support_email",
            field=models.CharField(blank=True, max_length=254),
        ),
    ]
