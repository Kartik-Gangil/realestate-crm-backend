from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("inventory", "0016_phase9_idempotency_constraints")]
    operations = [
        migrations.AddField(model_name="payment", name="advance_amount", field=models.DecimalField(decimal_places=2, default=0, max_digits=15)),
        migrations.AddField(model_name="payment", name="idempotency_key", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="payment", name="idempotency_request_hash", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AlterField(model_name="payment", name="status", field=models.CharField(choices=[("pending", "Pending"), ("pending_realization", "Pending Realization"), ("success", "Success"), ("failed", "Failed"), ("cancelled", "Cancelled"), ("refunded", "Refunded")], default="pending", max_length=24)),
        migrations.AddConstraint(model_name="payment", constraint=models.UniqueConstraint(fields=("organization", "project", "idempotency_key"), condition=~Q(idempotency_key="") & Q(project__isnull=False), name="inventory_payment_project_idempotency_unique")),
        migrations.AddConstraint(model_name="payment", constraint=models.UniqueConstraint(fields=("organization", "idempotency_key"), condition=~Q(idempotency_key="") & Q(project__isnull=True), name="inventory_payment_legacy_idempotency_unique")),
    ]
