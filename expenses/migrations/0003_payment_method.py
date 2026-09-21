from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("expenses", "0002_align_initial_model_state")]
    operations = [
        migrations.AddField(
            model_name="payment",
            name="payment_method",
            field=models.CharField(choices=[("cash", "Cash"), ("card", "Card"), ("bank_transfer", "Bank Transfer"), ("upi", "UPI")], default="bank_transfer", max_length=20),
            preserve_default=False,
        ),
    ]
