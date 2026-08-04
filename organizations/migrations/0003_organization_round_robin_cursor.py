from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_organizationmembership_tab_permissions")]
    operations = [migrations.AddField(model_name="organization", name="round_robin_cursor", field=models.PositiveBigIntegerField(blank=True, null=True))]