from django.db import migrations, models


def backfill_site_visit_projects(apps, schema_editor):
    Sitevisit = apps.get_model("leads", "Sitevisit")
    for visit in Sitevisit.objects.select_related("lead").filter(project__isnull=True):
        if visit.lead.project_id:
            Sitevisit.objects.filter(pk=visit.pk).update(project_id=visit.lead.project_id)


class Migration(migrations.Migration):
    dependencies = [("leads", "0020_lead_project"), ("inventory", "0008_restore_project_context")]

    operations = [
        migrations.AddField(
            model_name="sitevisit",
            name="project",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="site_visits", to="inventory.project"),
        ),
        migrations.RunPython(backfill_site_visit_projects, migrations.RunPython.noop),
    ]
