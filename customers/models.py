from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from organizations.models import ProjectScopedModel


class Customer(ProjectScopedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        ACTIVE = "active", "Active"
        ENGAGED = "engaged", "Engaged"
        CONVERTED = "converted", "Converted"
        INACTIVE = "inactive", "Inactive"
        BLACKLISTED = "blacklisted", "Blacklisted"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customers")
    lead = models.OneToOneField("leads.Lead", null=True, blank=True, on_delete=models.PROTECT, related_name="customer_profile")
    customer_code = models.CharField(max_length=40, unique=True, blank=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, default="")
    government_id = models.CharField(max_length=100, blank=True, default="")
    address = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    status_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "project", "phone"], name="customer_phone_unique"),
            models.UniqueConstraint(fields=["organization", "project", "email"], condition=~Q(email=""), name="customer_email_unique"),
            models.UniqueConstraint(fields=["organization", "project", "government_id"], condition=~Q(government_id=""), name="customer_govid_unique"),
        ]
        indexes = [models.Index(fields=["organization", "status"]), models.Index(fields=["organization", "phone"])]

    def save(self, *args, **kwargs):
        if self.lead_id and self.organization_id != self.lead.organization_id:
            raise ValidationError({"lead": "Lead must belong to this organization."})
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.customer_code:
            self.customer_code = f"CUS-{self.organization_id}-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(customer_code=self.customer_code)

    def delete(self, *args, **kwargs):
        raise ValidationError("Customer records are never hard-deleted.")

    def __str__(self):
        return f"{self.customer_code or 'new'} - {self.full_name}"


class CustomerNote(ProjectScopedModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="customer_notes")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="customer_notes")
    note_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
