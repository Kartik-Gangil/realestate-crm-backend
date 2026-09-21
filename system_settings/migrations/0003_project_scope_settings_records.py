import django.db.models.deletion
from django.db import migrations, models


PROJECT_FIELD = models.ForeignKey(
    blank=True,
    null=True,
    on_delete=django.db.models.deletion.PROTECT,
    related_name="%(app_label)s_%(class)s_records",
    to="organizations.project",
)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0013_project_scope_hr_records"),
        ("system_settings", "0002_seed_call_dispositions"),
    ]
    operations = [
        migrations.RemoveConstraint(model_name="integrationconfiguration", name="settings_integration_unique"),
        migrations.RemoveConstraint(model_name="masterdata", name="settings_master_code_unique"),
        migrations.RemoveConstraint(model_name="systemparameter", name="settings_parameter_key_unique"),
    ] + [
        migrations.AddField(model_name=model_name, name="project", field=PROJECT_FIELD.clone())
        for model_name in ("auditlog", "integrationconfiguration", "masterdata", "systemparameter")
    ] + [
        migrations.AddConstraint(model_name="integrationconfiguration", constraint=models.UniqueConstraint(fields=("organization", "project", "integration_type", "name"), name="settings_integration_unique")),
        migrations.AddConstraint(model_name="integrationconfiguration", constraint=models.UniqueConstraint(fields=("organization", "integration_type", "name"), condition=models.Q(project__isnull=True), name="settings_integration_legacy")),
        migrations.AddConstraint(model_name="masterdata", constraint=models.UniqueConstraint(fields=("organization", "project", "master_type", "code"), name="settings_master_code_unique")),
        migrations.AddConstraint(model_name="masterdata", constraint=models.UniqueConstraint(fields=("organization", "master_type", "code"), condition=models.Q(project__isnull=True), name="settings_master_code_legacy")),
        migrations.AddConstraint(model_name="systemparameter", constraint=models.UniqueConstraint(fields=("organization", "project", "parameter_key"), name="settings_parameter_key_unique")),
        migrations.AddConstraint(model_name="systemparameter", constraint=models.UniqueConstraint(fields=("organization", "parameter_key"), condition=models.Q(project__isnull=True), name="settings_parameter_key_legacy")),
    ]
