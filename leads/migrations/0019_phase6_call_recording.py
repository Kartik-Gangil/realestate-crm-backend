from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0018_alter_sitevisit_options_sitevisit_cancellation_notes_and_more")]

    operations = [
        migrations.AddField(
            model_name="followupcall",
            name="call_recording",
            field=models.FileField(blank=True, null=True, upload_to="call_recordings/%Y/%m/"),
        ),
    ]
