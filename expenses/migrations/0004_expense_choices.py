from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("expenses", "0003_phase16_workflow")]

    operations = [
        migrations.AlterField(
            model_name="expense",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash", "Cash"),
                    ("card", "Card"),
                    ("bank_transfer", "Bank Transfer"),
                    ("upi", "UPI"),
                ],
                default="cash",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="expense",
            name="payment_status",
            field=models.CharField(
                choices=[("unpaid", "Unpaid"), ("paid", "Paid")],
                default="unpaid",
                max_length=12,
            ),
        ),
    ]
