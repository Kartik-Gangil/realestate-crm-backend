from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("inventory", "0015_phase9_model_alignment")]

    operations = [
        migrations.AddConstraint(
            model_name="plotbooking",
            constraint=models.UniqueConstraint(
                condition=~Q(idempotency_key="") & Q(project__isnull=False),
                fields=("organization", "project", "idempotency_key"),
                name="inventory_booking_project_idempotency_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="plotbooking",
            constraint=models.UniqueConstraint(
                condition=~Q(idempotency_key="") & Q(project__isnull=True),
                fields=("organization", "idempotency_key"),
                name="inventory_booking_legacy_idempotency_unique",
            ),
        ),
    ]
