from django.db import migrations
from django.utils import timezone


def mark_old_reminders_sent(apps, schema_editor):
    FollowUpCall = apps.get_model("leads", "FollowUpCall")
    Sitevisit = apps.get_model("leads", "Sitevisit")
    migration_time = timezone.now()
    today = timezone.localdate()
    FollowUpCall.objects.filter(next_follow_up__lt=migration_time).update(reminder_sent=True)
    Sitevisit.objects.filter(
        visit_date__lt=today,
        reminder_sent_at__isnull=True,
    ).update(reminder_sent_at=migration_time)


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0033_reminder_flags"),
    ]

    operations = [
        migrations.RunPython(mark_old_reminders_sent, migrations.RunPython.noop),
    ]
