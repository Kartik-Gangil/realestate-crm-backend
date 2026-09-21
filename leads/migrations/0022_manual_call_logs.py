from django.db import migrations, models

import leads.models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0021_followupreminder_followupcall_reminder_sent"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="followupcall",
            name="leads_one_active_call",
        ),
        migrations.RemoveField(
            model_name="followupcall",
            name="started_at",
        ),
        migrations.RemoveField(
            model_name="followupcall",
            name="duration_seconds",
        ),
        migrations.AddField(
            model_name="followupcall",
            name="call_recording",
            field=models.FileField(blank=True, upload_to=leads.models.call_recording_upload_to),
        ),
    ]
