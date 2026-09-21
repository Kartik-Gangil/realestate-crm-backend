import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0013_dynamic_plot_status"),
        ("leads", "0027_phase5_lead_lifecycle"),
        ("organizations", "0014_organizationmembership_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="plotbooking", name="idempotency_key", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="plotbooking", name="idempotency_request_hash", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField(model_name="plotbooking", name="hold_expires_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="plotbooking", name="minimum_payment_amount", field=models.DecimalField(decimal_places=2, default=0, max_digits=15)),
        migrations.AlterField(model_name="plotbooking", name="status", field=models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled"), ("expired", "Expired")], default="pending", max_length=16)),
        migrations.AddIndex(model_name="plotbooking", index=models.Index(fields=["organization", "idempotency_key"], name="inventory_p_org_idem_9f8b31_idx")),
        migrations.AddIndex(model_name="plotbooking", index=models.Index(fields=["status", "hold_expires_at"], name="inventory_p_status_hold_1e46d8_idx")),
        migrations.CreateModel(
            name="BookingReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveBigIntegerField()),
                ("receipt_number", models.CharField(max_length=48)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="inventory_bookingreceipt_records", to="organizations.project")),
                ("booking", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="receipt", to="inventory.plotbooking")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="booking_receipts", to="organizations.organization")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("organization", "project", "sequence"), name="inventory_booking_receipt_org_sequence_unique"), models.UniqueConstraint(condition=Q(project__isnull=True), fields=("organization", "sequence"), name="inventory_booking_receipt_org_sequence_legacy")]},
        ),
    ]
