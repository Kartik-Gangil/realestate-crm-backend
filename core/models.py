import uuid

from django.db import models
from django.core.exceptions import ValidationError


class TaskRecord(models.Model):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        RUNNING = "RUNNING", "Running"
        FAILED = "FAILED", "Failed"
        SUCCESSFUL = "SUCCESSFUL", "Successful"

    id = models.CharField(primary_key=True, max_length=64, default=uuid.uuid4)
    task_path = models.CharField(max_length=512)
    queue_name = models.CharField(max_length=100, default="default")
    priority = models.SmallIntegerField(default=0)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    run_after = models.DateTimeField()
    enqueued_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.READY)
    worker_ids = models.JSONField(default=list)
    return_value = models.JSONField(null=True, blank=True)
    error_type = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("status", "run_after", "priority", "enqueued_at")),
        ]


class Notification(models.Model):
    """Pending in-app notification used by the Phase 0 fallback."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READ = "read", "Read"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="notifications"
    )
    project = models.ForeignKey(
        "inventory.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )
    recipient_membership = models.ForeignKey(
        "organizations.OrganizationMembership", on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    body = models.TextField()
    related_object_type = models.CharField(max_length=150, blank=True)
    related_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=("recipient_membership", "status", "-created_at")),
            models.Index(fields=("organization", "project", "-created_at")),
        ]

    def clean(self):
        super().clean()
        if self.recipient_membership_id and self.recipient_membership.organization_id != self.organization_id:
            raise ValidationError({"recipient_membership": "Recipient must belong to the notification organization."})
        if self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError({"project": "Project must belong to the notification organization."})
