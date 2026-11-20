from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("inventory", "0017_phase9_customers_booking_lifecycle")]

    operations = [
        migrations.RenameIndex(
            model_name="customer",
            new_name="inventory_c_organiz_8de5a1_idx",
            old_name="inventory_cust_org_proj_lead_idx",
        ),
    ]
