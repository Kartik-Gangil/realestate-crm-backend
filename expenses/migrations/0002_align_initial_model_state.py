import datetime

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("expenses", "0001_initial")]
    operations = [
        migrations.RenameIndex(
            model_name="expense",
            new_name="expenses_ex_organiz_37d180_idx",
            old_name="expenses_ex_organiz_9e8b9f_idx",
        ),
        migrations.RenameIndex(
            model_name="expense",
            new_name="expenses_ex_organiz_9ac713_idx",
            old_name="expenses_ex_organiz_3a0e4e_idx",
        ),
        migrations.RenameIndex(
            model_name="expense",
            new_name="expenses_ex_organiz_b7331e_idx",
            old_name="expenses_ex_organiz_7c3d6b_idx",
        ),
        migrations.AlterField(
            model_name="expense",
            name="date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
