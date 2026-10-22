from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_restore_project_relations")]

    operations = [
        migrations.CreateModel(
            name="PaymentAdvance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("booking", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_advances", to="inventory.plotbooking")),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payment_advances", to="inventory.payment")),
            ],
            options={
                "indexes": [models.Index(fields=["booking", "payment"], name="inventory_p_booking_advance_idx")],
                "constraints": [models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="inventory_payment_advance_positive")],
            },
        ),
    ]
