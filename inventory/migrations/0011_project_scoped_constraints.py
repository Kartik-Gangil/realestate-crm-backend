from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0010_agreement_project_block_project_installment_project_and_more")]

    operations = [
        migrations.RemoveConstraint(model_name=model_name, name=constraint_name)
        for model_name, constraint_name in (
            ("block", "unique_inventory_block_code"),
            ("payment", "inventory_payment_org_payment_id_unique"),
            ("paymentreceipt", "inventory_receipt_org_number_unique"),
            ("plot", "unique_inventory_plot_number"),
            ("recentlyviewedplot", "unique_recently_viewed_plot"),
        )
    ] + [
        migrations.AddConstraint(
            model_name="block",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "code"), name="unique_inventory_block_code"
            ),
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "payment_id"),
                name="inventory_payment_org_payment_id_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="paymentreceipt",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "receipt_number"),
                name="inventory_receipt_org_number_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="plot",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "block", "plot_number"),
                name="unique_inventory_plot_number",
            ),
        ),
        migrations.AddConstraint(
            model_name="recentlyviewedplot",
            constraint=models.UniqueConstraint(
                fields=("organization", "project", "user", "plot"),
                name="unique_recently_viewed_plot",
            ),
        ),
    ]
