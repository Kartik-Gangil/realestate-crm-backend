from django.db import migrations, models

def create_pending_calls(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    FollowUpCall = apps.get_model("leads", "FollowUpCall")
    for lead in Lead.objects.exclude(assigned_membership__isnull=True).iterator():
        if not FollowUpCall.objects.filter(lead_id=lead.id, called_at__isnull=True).exists():
            FollowUpCall.objects.create(organization_id=lead.organization_id, lead_id=lead.id, telecaller_membership_id=lead.assigned_membership_id, note="", outcome="", called_at=None)

class Migration(migrations.Migration):
    dependencies = [("leads", "0004_require_organization")]
    operations = [
        migrations.AlterField(model_name="followupcall", name="note", field=models.TextField(blank=True, default="")),
        migrations.AlterField(model_name="followupcall", name="outcome", field=models.CharField(blank=True, choices=[("connected", "Connected"), ("no_answer", "No answer"), ("busy", "Busy"), ("callback", "Callback requested"), ("not_interested", "Not interested"), ("invalid_number", "Invalid number")], default="", max_length=20)),
        migrations.AlterField(model_name="followupcall", name="called_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.RunPython(create_pending_calls, migrations.RunPython.noop),
    ]