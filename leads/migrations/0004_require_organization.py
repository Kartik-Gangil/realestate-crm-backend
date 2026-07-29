from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0003_remove_followupcall_leads_follo_lead_id_c4f04d_idx_and_more")]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="leads", to="organizations.organization"),
        ),
        migrations.AlterField(
            model_name="followupcall",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="follow_up_calls", to="organizations.organization"),
        ),
    ]