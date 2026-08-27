from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("organizations", "0007_organizationmembership_organization_role")]

    operations = [
        migrations.RemoveField(
            model_name="organizationmembership",
            name="tab_permissions",
        ),
    ]