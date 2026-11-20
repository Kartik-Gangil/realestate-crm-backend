from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_booking_phase9(apps, schema_editor):
    PlotBooking = apps.get_model("inventory", "PlotBooking")
    for booking in PlotBooking.objects.select_related("plot").all().iterator():
        updates = {"project_id": booking.plot.project_id}
        if booking.status == "pending":
            updates["status"] = "payment_pending"
        PlotBooking.objects.filter(pk=booking.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0016_plot_hold_expiry"),
        ("leads", "0034_mark_old_reminders_sent"),
        ("organizations", "0027_phase8_plot_hold_permission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_code", models.CharField(max_length=64)),
                ("full_name", models.CharField(max_length=255)),
                ("phone", models.CharField(blank=True, max_length=64)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("address", models.TextField(blank=True)),
                ("status", models.CharField(default="active", max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_records", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inventory_customers", to="organizations.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customers", to="inventory.project")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("project", "customer_code"), name="inventory_customer_project_code_unique")],
                "indexes": [models.Index(fields=("organization", "project", "lead"), name="inventory_cust_org_proj_lead_idx")],
            },
        ),
        migrations.CreateModel(
            name="CustomerCodeSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_number", models.PositiveIntegerField(default=1)),
                ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="customer_code_sequence", to="inventory.project")),
            ],
        ),
        migrations.CreateModel(
            name="BookingReceiptSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_number", models.PositiveIntegerField(default=1)),
                ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="booking_receipt_sequence", to="inventory.project")),
            ],
        ),
        migrations.AddField(model_name="plotbooking", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="inventory.project")),
        migrations.AddField(model_name="plotbooking", name="customer", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bookings", to="inventory.customer")),
        migrations.AddField(model_name="plotbooking", name="booking_code", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="plotbooking", name="booking_date", field=models.DateField(default=django.utils.timezone.localdate)),
        migrations.AddField(model_name="plotbooking", name="total_amount", field=models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True)),
        migrations.AddField(model_name="plotbooking", name="discount_amount", field=models.DecimalField(decimal_places=2, default=0, max_digits=16)),
        migrations.AddField(model_name="plotbooking", name="net_amount", field=models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True)),
        migrations.AddField(model_name="plotbooking", name="booking_amount_paid", field=models.DecimalField(decimal_places=2, default=0, max_digits=16)),
        migrations.AddField(model_name="plotbooking", name="hold_expires_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="plotbooking", name="booking_receipt_number", field=models.CharField(blank=True, max_length=64)),
        migrations.AlterField(model_name="plotbooking", name="status", field=models.CharField(choices=[("created", "Created"), ("payment_pending", "Payment Pending"), ("partially_paid", "Partially Paid"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled"), ("expired", "Expired")], default="payment_pending", max_length=16)),
        migrations.CreateModel(
            name="BookingIdempotencyKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=255)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("booking", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="idempotency_records", to="inventory.plotbooking")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="booking_idempotency_keys", to="organizations.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="booking_idempotency_keys", to="inventory.project")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("organization", "project", "key"), name="inventory_booking_idempotency_unique")]},
        ),
        migrations.RunPython(backfill_booking_phase9, migrations.RunPython.noop),
    ]
