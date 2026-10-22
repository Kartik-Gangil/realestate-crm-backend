from django.conf import settings
from django.core import validators
from django.db import migrations, models
import django.db.models.deletion


def agreement_signed_upload_path(instance, filename):
    from inventory.models import agreement_signed_upload_path as upload_path
    return upload_path(instance, filename)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0010_paymentadvance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AgreementSignedDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to=agreement_signed_upload_path, validators=[validators.FileExtensionValidator(["pdf", "jpg", "jpeg", "png"])])),
                ("original_filename", models.CharField(max_length=255)),
                ("content_type", models.CharField(max_length=100)),
                ("file_size_bytes", models.PositiveBigIntegerField()),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("agreement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="signed_documents", to="inventory.agreement")),
                ("uploaded_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_agreement_signed_documents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-uploaded_at", "-id"], "indexes": [models.Index(fields=["agreement", "superseded_at"], name="inventory_a_agreement_5b4f48_idx")]},
        ),
    ]
