import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("documents", "0006_documentexpirynotification_ekycverification"), ("organizations", "0014_organizationmembership_projects")]

    operations = [
        migrations.RenameIndex(model_name="documentexpirynotification", old_name="documents_do_organ_4b9a7b_idx", new_name="documents_d_organiz_7b8b94_idx"),
        migrations.RenameIndex(model_name="ekycverification", old_name="documents_ek_organ_8b4fcb_idx", new_name="documents_e_organiz_4f82b8_idx"),
        migrations.AlterField(model_name="documentexpirynotification", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
        migrations.AlterField(model_name="ekycverification", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
    ]
