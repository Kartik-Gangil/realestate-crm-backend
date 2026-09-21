from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("leads", "0020_alter_followupcall_outcome")]
    operations = [
        migrations.AddField(
            model_name="followupcall",
            name="reminder_sent",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="FollowUpReminder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scheduled_for", models.DateTimeField()),
                ("event_type", models.CharField(default="telecalling.follow_up_due", max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("dispatched", "Dispatched"), ("failed", "Failed"), ("cancelled", "Cancelled")], default="pending", max_length=16)),
                ("payload", models.JSONField(default=dict)),
                ("dispatched_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("follow_up", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="reminder", to="leads.followupcall")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="follow_up_reminders", to="organizations.organization")),
                ("recipient_membership", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="follow_up_reminders", to="organizations.organizationmembership")),
            ],
            options={
                "ordering": ["scheduled_for", "id"],
                "indexes": [models.Index(fields=["organization", "status", "scheduled_for"], name="leads_reminder_due_idx")],
            },
        ),
    ]
