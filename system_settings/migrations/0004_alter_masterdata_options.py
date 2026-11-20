from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("system_settings", "0003_phase2_categories_parameters")]

    operations = [
        migrations.AlterModelOptions(
            name="masterdata",
            options={"ordering": ("category__code", "sort_order", "name")},
        ),
    ]
