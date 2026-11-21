import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inventory", "0018_rename_customer_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customer",
            name="lead",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_records",
                to="leads.lead",
            ),
        ),
        migrations.AlterField(
            model_name="customer",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "New"), ("active", "Active"), ("engaged", "Engaged"),
                    ("converted", "Converted"), ("inactive", "Inactive"), ("blacklisted", "Blacklisted"),
                ],
                default="new",
                max_length=24,
            ),
        ),
        migrations.AddField(model_name="customer", name="government_id_encrypted", field=models.TextField(blank=True)),
        migrations.AddField(model_name="customer", name="government_id_hash", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="customer", name="government_id_last4", field=models.CharField(blank=True, max_length=4)),
        migrations.AddField(
            model_name="customer", name="government_id_type",
            field=models.CharField(blank=True, choices=[("aadhaar", "Aadhaar"), ("pan", "PAN")], max_length=16),
        ),
        migrations.AddField(model_name="customer", name="lifecycle_reason", field=models.TextField(blank=True)),
        migrations.AddField(model_name="customer", name="lifecycle_changed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name="customer", name="lifecycle_changed_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="customer_lifecycle_changes", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(model_name="customer", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.CreateModel(
            name="CustomerNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note_text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customer_notes", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="notes", to="inventory.customer")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
