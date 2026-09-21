from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0019_followupcall_session_fields")]
    operations = [
        migrations.AlterField(
            model_name="followupcall",
            name="outcome",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
