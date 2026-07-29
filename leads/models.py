from django.conf import settings
from django.db import models
from django.utils import timezone


class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        SITE_VISIT = "site_visit", "Site Visit"
        NEGOTIATION = "negotiation", "Negotiation"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    class Source(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        WEBSITE = "website", "Website"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="leads")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    next_follow_up = models.DateTimeField(null=True, blank=True)
    assigned_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_leads")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "source"]),
            models.Index(fields=["organization", "assigned_membership", "status"]),
            models.Index(fields=["organization", "next_follow_up"]),
        ]

    @property
    def full_name(self):
        return " ".join(part for part in [self.first_name, self.last_name] if part)

    def clean(self):
        if self.assigned_membership_id and self.assigned_membership.organization_id != self.organization_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"assigned_membership": "Assignee must belong to this organization."})

    def __str__(self):
        return self.full_name


class FollowUpCall(models.Model):
    class Outcome(models.TextChoices):
        CONNECTED = "connected", "Connected"
        NO_ANSWER = "no_answer", "No answer"
        BUSY = "busy", "Busy"
        CALLBACK = "callback", "Callback requested"
        NOT_INTERESTED = "not_interested", "Not interested"
        INVALID_NUMBER = "invalid_number", "Invalid number"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="follow_up_calls")
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="follow_up_calls")
    telecaller_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, on_delete=models.SET_NULL, related_name="follow_up_calls")
    note = models.TextField()
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.CONNECTED)
    called_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-called_at", "-id"]
        indexes = [models.Index(fields=["organization", "lead", "called_at"])]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.lead_id and self.organization_id != self.lead.organization_id:
            raise ValidationError({"organization": "Call organization must match the lead organization."})
        if self.telecaller_membership_id and self.telecaller_membership.organization_id != self.organization_id:
            raise ValidationError({"telecaller_membership": "Telecaller must belong to this organization."})

    def __str__(self):
        return f"{self.lead} - {self.get_outcome_display()}"