from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0014_phase9_booking_controls"),
        ("organizations", "0014_organizationmembership_projects"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="plotbooking",
            new_name="inventory_p_organiz_aaceeb_idx",
            old_name="inventory_p_org_idem_9f8b31_idx",
        ),
        migrations.RenameIndex(
            model_name="plotbooking",
            new_name="inventory_p_status_33e783_idx",
            old_name="inventory_p_status_hold_1e46d8_idx",
        ),
        migrations.AlterField(
            model_name="bookingreceipt",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_records",
                to="organizations.project",
            ),
        ),
    ]
