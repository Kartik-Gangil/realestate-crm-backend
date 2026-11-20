from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0032_protect_lead_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="followupcall",
            name="reminder_sent",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name="sitevisit",
            name="reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
