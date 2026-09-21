import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0001_phase10_customer_360"), ("organizations", "0014_organizationmembership_projects")]
    operations = [
        migrations.RenameIndex(model_name="customer", old_name="customers_c_organiz_1f5d7e_idx", new_name="customers_c_organiz_628fa0_idx"),
        migrations.RenameIndex(model_name="customer", old_name="customers_c_organiz_7c4f7b_idx", new_name="customers_c_organiz_d39d52_idx"),
        migrations.AlterField(model_name="customer", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
        migrations.AlterField(model_name="customernote", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
    ]
