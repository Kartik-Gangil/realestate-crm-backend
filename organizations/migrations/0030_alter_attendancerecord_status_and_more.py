from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0029_group_e_roles_hr_and_accounts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendancerecord",
            name="status",
            field=models.CharField(
                choices=[
                    ("present", "Present"),
                    ("late", "Late"),
                    ("incomplete", "Incomplete"),
                    ("absent", "Absent"),
                ],
                default="present",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="leaverequest",
            name="leave_type",
            field=models.CharField(
                choices=[
                    ("casual", "Casual"),
                    ("sick", "Sick"),
                    ("paid", "Paid"),
                    ("earned", "Earned"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="organizationmembership",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("manager", "Manager"),
                    ("telecaller", "Telecaller"),
                    ("site-visit-executive", "Site Visit Executive"),
                    ("hr-admin", "HR Admin"),
                    ("accounts", "Accounts"),
                ],
                default="telecaller",
                max_length=40,
            ),
        ),
        migrations.CreateModel(
            name="LeaveBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("leave_type", models.CharField(max_length=16)),
                ("year", models.PositiveSmallIntegerField()),
                ("allocated_days", models.PositiveSmallIntegerField(default=0)),
                ("used_days", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leave_balances",
                        to="organizations.organizationmembership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leave_balances",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("employee", "leave_type", "year"),
                        name="employee_leave_balance_year_type_unique",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PerformanceReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quarter", models.CharField(max_length=7)),
                ("rating", models.PositiveSmallIntegerField()),
                ("comments", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_reviews",
                        to="organizations.organizationmembership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_reviews",
                        to="organizations.organization",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authored_performance_reviews",
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("employee", "quarter"),
                        name="employee_performance_review_quarter_unique",
                    ),
                ],
            },
        ),
    ]
