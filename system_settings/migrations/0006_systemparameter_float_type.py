from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("system_settings", "0005_masterdata_is_system"),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemparameter",
            name="data_type",
            field=models.CharField(
                choices=[
                    ("string", "String"),
                    ("integer", "Integer"),
                    ("float", "Float"),
                    ("decimal", "Decimal"),
                    ("boolean", "Boolean"),
                    ("json", "JSON"),
                ],
                max_length=16,
            ),
        ),
    ]
