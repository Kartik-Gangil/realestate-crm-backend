from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0005_legacy_unassigned_constraints"),
        ("leads", "0028_phase9_booking_gates"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentExpiryNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="documents_documentexpirynotification_records", to="organizations.project")),
                ("channel", models.CharField(choices=[("email", "Email"), ("sms", "SMS")], max_length=12)),
                ("recipient", models.CharField(max_length=255)),
                ("alert_date", models.DateField()),
                ("scheduled_for", models.DateTimeField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=12)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expiry_notifications", to="documents.customerdocument")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="document_expiry_notifications", to="organizations.organization")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("document", "channel", "alert_date"), name="documents_expiry_notification_unique")], "indexes": [models.Index(fields=["organization", "status", "scheduled_for"], name="documents_do_organ_4b9a7b_idx")]},
        ),
        migrations.CreateModel(
            name="EkycVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="documents_ekycverification_records", to="organizations.project")),
                ("provider", models.CharField(default="mock", max_length=40)),
                ("id_number_encrypted", models.TextField(blank=True)),
                ("verification_status", models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("failed", "Failed")], default="pending", max_length=16)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("face_match_score", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=255)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ekyc_verifications", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ekyc_verifications", to="organizations.organization")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_ekyc_verifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"], "indexes": [models.Index(fields=["organization", "customer", "verification_status"], name="documents_ek_organ_8b4fcb_idx")]},
        ),
    ]
