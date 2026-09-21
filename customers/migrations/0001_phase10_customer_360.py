import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("leads", "0028_phase9_booking_gates"),
        ("organizations", "0014_organizationmembership_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_code", models.CharField(blank=True, max_length=40, unique=True)),
                ("full_name", models.CharField(max_length=200)),
                ("phone", models.CharField(max_length=20)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("government_id", models.CharField(blank=True, default="", max_length=100)),
                ("address", models.CharField(blank=True, default="", max_length=300)),
                ("status", models.CharField(choices=[("new", "New"), ("active", "Active"), ("engaged", "Engaged"), ("converted", "Converted"), ("inactive", "Inactive"), ("blacklisted", "Blacklisted")], default="new", max_length=16)),
                ("status_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customers_customer_records", to="organizations.project")),
                ("lead", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customer_profile", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="customers", to="organizations.organization")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="CustomerNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note_text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="customers_customernote_records", to="organizations.project")),
                ("author", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_notes", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="customer_notes", to="organizations.organization")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="notes", to="customers.customer")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint(model_name="customer", constraint=models.UniqueConstraint(fields=("organization", "project", "phone"), name="customer_phone_unique")),
        migrations.AddConstraint(model_name="customer", constraint=models.UniqueConstraint(condition=~Q(email=""), fields=("organization", "project", "email"), name="customer_email_unique")),
        migrations.AddConstraint(model_name="customer", constraint=models.UniqueConstraint(condition=~Q(government_id=""), fields=("organization", "project", "government_id"), name="customer_govid_unique")),
        migrations.AddIndex(model_name="customer", index=models.Index(fields=["organization", "status"], name="customers_c_organiz_1f5d7e_idx")),
        migrations.AddIndex(model_name="customer", index=models.Index(fields=["organization", "phone"], name="customers_c_organiz_7c4f7b_idx")),
    ]
