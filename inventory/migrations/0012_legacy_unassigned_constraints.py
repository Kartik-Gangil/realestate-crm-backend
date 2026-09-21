from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_project_scoped_constraints")]
    operations = [
        migrations.AddConstraint(model_name="block", constraint=models.UniqueConstraint(fields=("organization", "code"), condition=models.Q(project__isnull=True), name="unique_inventory_block_code_legacy")),
        migrations.AddConstraint(model_name="payment", constraint=models.UniqueConstraint(fields=("organization", "payment_id"), condition=models.Q(project__isnull=True), name="inventory_payment_org_payment_id_legacy")),
        migrations.AddConstraint(model_name="paymentreceipt", constraint=models.UniqueConstraint(fields=("organization", "receipt_number"), condition=models.Q(project__isnull=True), name="inventory_receipt_org_number_legacy")),
        migrations.AddConstraint(model_name="plot", constraint=models.UniqueConstraint(fields=("organization", "block", "plot_number"), condition=models.Q(project__isnull=True), name="unique_inventory_plot_number_legacy")),
        migrations.AddConstraint(model_name="recentlyviewedplot", constraint=models.UniqueConstraint(fields=("organization", "user", "plot"), condition=models.Q(project__isnull=True), name="unique_recently_viewed_plot_legacy")),
    ]
