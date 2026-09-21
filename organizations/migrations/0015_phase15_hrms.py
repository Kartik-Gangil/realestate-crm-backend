from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("organizations", "0014_organizationmembership_projects"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(model_name="leaverequest", name="leave_type", field=models.CharField(choices=[("casual", "Casual Leave"), ("sick", "Sick Leave"), ("paid", "Paid Leave"), ("earned", "Earned Leave")], max_length=16)),
        migrations.CreateModel(
            name="EmployeeLeaveBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
                ("leave_type", models.CharField(choices=[("casual", "Casual Leave"), ("sick", "Sick Leave"), ("paid", "Paid Leave"), ("earned", "Earned Leave")], max_length=16)),
                ("allocated_days", models.PositiveIntegerField(default=0)), ("used_days", models.PositiveIntegerField(default=0)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leave_balances", to="organizations.organizationmembership")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="employee_leave_balances", to="organizations.organization")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("organization", "project", "employee", "leave_type"), name="employee_leave_balance_unique"), models.UniqueConstraint(condition=models.Q(project__isnull=True), fields=("organization", "employee", "leave_type"), name="employee_leave_balance_legacy")]},
        ),
        migrations.CreateModel(
            name="PerformanceReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_records", to="organizations.project")),
                ("quarter", models.CharField(max_length=7)), ("rating", models.PositiveSmallIntegerField()), ("comments", models.TextField(blank=True)), ("reviewed_at", models.DateTimeField(auto_now_add=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="performance_reviews", to="organizations.organizationmembership")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="performance_reviews", to="organizations.organization")),
                ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="submitted_performance_reviews", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-reviewed_at", "-id"], "constraints": [models.UniqueConstraint(fields=("organization", "project", "employee", "quarter"), name="employee_performance_quarter_unique"), models.UniqueConstraint(condition=models.Q(project__isnull=True), fields=("organization", "employee", "quarter"), name="employee_performance_quarter_legacy")]},
        ),
    ]
