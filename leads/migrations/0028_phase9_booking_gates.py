from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0027_phase5_lead_lifecycle")]

    operations = [
        migrations.AddField(model_name="lead", name="is_qualified", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="lead", name="ekyc_status", field=models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("rejected", "Rejected"), ("expired", "Expired")], default="verified", max_length=16)),
    ]
