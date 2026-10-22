import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_employee_phase2"),
        ("inventory", "0011_agreementsigneddocument"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RegistryDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(blank=True, null=True, upload_to="inventory.models.registry_document_upload_path", validators=[django.core.validators.FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])])),
                ("document_label", models.CharField(max_length=200)),
                ("document_type", models.CharField(default="other", max_length=100)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=100)),
                ("file_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("customer_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="registry_attachments", to="documents.customerdocument")),
                ("registry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="inventory.registry")),
                ("uploaded_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_registry_documents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
