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
    dependencies = [("organizations", "0012_organization_code_organization_status_project")]
    operations = [
        migrations.RemoveConstraint(model_name="attendancerecord", name="employee_daily_attendance_unique"),
        migrations.RemoveConstraint(model_name="organizationholiday", name="organization_holiday_date_unique"),
    ] + [
        migrations.AddField(model_name=model_name, name="project", field=PROJECT_FIELD.clone())
        for model_name in ("attendancerecord", "leaverequest", "organizationactivity", "organizationholiday")
    ] + [
        migrations.AddConstraint(model_name="attendancerecord", constraint=models.UniqueConstraint(fields=("project", "employee", "attendance_date"), name="employee_daily_attendance_unique")),
        migrations.AddConstraint(model_name="attendancerecord", constraint=models.UniqueConstraint(fields=("employee", "attendance_date"), condition=models.Q(project__isnull=True), name="employee_daily_attendance_legacy")),
        migrations.AddConstraint(model_name="organizationholiday", constraint=models.UniqueConstraint(fields=("organization", "project", "holiday_date"), name="organization_holiday_date_unique")),
        migrations.AddConstraint(model_name="organizationholiday", constraint=models.UniqueConstraint(fields=("organization", "holiday_date"), condition=models.Q(project__isnull=True), name="organization_holiday_date_legacy")),
    ]
