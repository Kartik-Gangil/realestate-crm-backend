from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0018_alter_sitevisit_options_sitevisit_cancellation_notes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="followupcall",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="followupcall",
            name="duration_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="followupcall",
            index=models.Index(
                fields=["organization", "telecaller_membership", "called_at"],
                name="leads_follo_organiz_02676e_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="followupcall",
            constraint=models.UniqueConstraint(
                condition=models.Q(started_at__isnull=False, called_at__isnull=True),
                fields=("organization", "telecaller_membership"),
                name="leads_one_active_call",
            ),
        ),
    ]
