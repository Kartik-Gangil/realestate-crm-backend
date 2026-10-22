from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Lead(models.Model):

    class Source(models.TextChoices):
        FACEBOOK = "fb", "Facebook"
        INSTAGRAM = "ig", "Instagram"
        WEBSITE = "website", "Website"
        SITEVISIT = "site_visit", "Site Visit"
        OTHER = "other", "Other"
        WALKIN = "walk_in", "Walk-in"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="leads")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20)
    alt_phone = models.CharField(max_length=20 , blank=True)
    address = models.CharField(max_length=200 , blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    assigned_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_leads")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "source"]),
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
class Sitevisit(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        UPCOMING = "upcoming", "Upcoming"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        RESCHEDULED = "rescheduled", "Rescheduled"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No show"

    class Outcome(models.TextChoices):
        INTERESTED = "interested", "Interested"
        NOT_INTERESTED = "not_interested", "Not interested"
        NEED_MORE_TIME = "need_more_time", "Need more time"
        PRICE_ISSUE = "price_issue", "Price issue"
        LOCATION_ISSUE = "location_issue", "Location issue"
        LOAN_ISSUE = "loan_issue", "Loan issue"
        ALREADY_PURCHASED = "already_purchased", "Already purchased"
        WRONG_REQUIREMENT = "wrong_requirement", "Wrong requirement"
        OTHER = "other", "Other"

    organization = models.ForeignKey("organizations.Organization" , on_delete=models.CASCADE, related_name="site_visit")
    project = models.ForeignKey("inventory.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="site_visits")
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE,related_name="site_visit")
    # An organization membership is the project's existing representation of a team member/executive.
    executive_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="site_visits")
    visit_date = models.DateField(null=True , blank=True)
    visit_time = models.TimeField(null=True , blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    site=models.TextField(null=True,blank=True)
    location=models.TextField(null=True,blank=True)
    customer_preference=models.TextField(null=True,blank=True)
    notes=models.TextField(null=True,blank=True)
    cancellation_reason = models.TextField(null=True , blank=True)
    cancellation_notes = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    outcome = models.CharField(max_length=30, choices=Outcome.choices, null=True, blank=True)
    interest_level = models.PositiveSmallIntegerField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_site_visits")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    def clean(self): 
        if self.lead_id and self.organization_id != self.lead.organization_id: 
            raise ValidationError({"organization": "Site visit organization must match the lead organization."})
        if self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError({"project": "Project must belong to the site visit organization."})
        if self.lead_id and self.project_id and self.lead.project_id and self.project_id != self.lead.project_id:
            raise ValidationError({"project": "Project must match the lead project."})
        if self.executive_membership_id and self.executive_membership.organization_id != self.organization_id:
            raise ValidationError({"executive_membership": "Executive must belong to this organization."})
        if self.duration_minutes is not None and self.duration_minutes == 0:
            raise ValidationError({"duration_minutes": "Duration must be greater than zero."})
        if self.interest_level is not None and not 1 <= self.interest_level <= 5:
            raise ValidationError({"interest_level": "Interest level must be between 1 and 5."})

    class Meta:
        ordering = ["visit_date", "visit_time", "id"]
        indexes = [
            models.Index(fields=["organization", "status", "visit_date"]),
            models.Index(fields=["organization", "executive_membership", "visit_date"]),
            models.Index(fields=["lead", "visit_date"]),
        ]

    def can_transition_to(self, new_status):
        allowed = {
            self.Status.SCHEDULED: {self.Status.UPCOMING, self.Status.IN_PROGRESS, self.Status.CANCELLED, self.Status.NO_SHOW},
            self.Status.UPCOMING: {self.Status.IN_PROGRESS, self.Status.CANCELLED, self.Status.NO_SHOW, self.Status.RESCHEDULED},
            self.Status.RESCHEDULED: {self.Status.UPCOMING, self.Status.IN_PROGRESS, self.Status.CANCELLED, self.Status.NO_SHOW},
            self.Status.IN_PROGRESS: {self.Status.COMPLETED, self.Status.CANCELLED},
            self.Status.COMPLETED: set(),
            self.Status.CANCELLED: set(),
            self.Status.NO_SHOW: set(),
        }
        return new_status in allowed.get(self.status, set())

    def transition_to(self, new_status):
        if not self.can_transition_to(new_status):
            raise ValidationError({"status": f"Cannot change a {self.status} visit to {new_status}."})
        self.status = new_status
    
    
class SitevisitReschedule(models.Model):
    site_visit = models.ForeignKey(
        Sitevisit,
        on_delete=models.CASCADE,
        related_name="reschedules"
    )

    old_date = models.DateField()
    old_time = models.TimeField()

    new_date = models.DateField()
    new_time = models.TimeField()

    reason = models.TextField(
        blank=True,
        null=True
    )

    rescheduled_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["-rescheduled_at", "-id"]

    def clean(self):
        """Keep each history entry tied to the schedule it replaced."""
        super().clean()
        if not self.site_visit_id:
            return

        if (self.old_date, self.old_time) != (
            self.site_visit.visit_date,
            self.site_visit.visit_time,
        ):
            raise ValidationError({
                "old_date": "Old date and time must match the current site-visit schedule.",
            })

        if (self.old_date, self.old_time) == (self.new_date, self.new_time):
            raise ValidationError({
                "new_date": "The new schedule must be different from the current schedule.",
            })

    @property
    def organization_id(self):
        """Expose the organization through the associated site visit."""
        return self.site_visit.organization_id


class FollowUpCall(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        SITE_VISIT = "site_visit", "Site Visit"
        NEGOTIATION = "negotiation", "Negotiation"
        WON = "won", "Won"
        LOST = "lost", "Lost"
    class Outcome(models.TextChoices):
        INTERESTED = "Interested", "Interested"
        CALLBACK_LATER = "Callback Later", "Callback Later"
        SWITCHED_OFF = "Switched Off", "Switched Off"
        WRONG_NUMBER = "Wrong Number", "Wrong Number"
        DND = "DND", "DND"
        ALREADY_PURCHASED = "Already Purchased", "Already Purchased"
        CONNECTED = "connected", "Connected"
        NO_ANSWER = "no_answer", "No answer"
        BUSY = "busy", "Busy"
        CALLBACK = "callback", "Callback requested"
        NOT_INTERESTED = "not_interested", "Not interested"
        INVALID_NUMBER = "invalid_number", "Invalid number"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="follow_up_calls")
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="follow_up_calls")
    telecaller_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, on_delete=models.SET_NULL, related_name="follow_up_calls")
    note = models.TextField(blank=True, default="")
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    next_follow_up = models.DateTimeField(null=True, blank=True)
    called_at = models.DateTimeField(null=True, blank=True)
    call_recording = models.FileField(upload_to="call_recordings/%Y/%m/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-called_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "lead", "called_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "next_follow_up"]),
            models.Index(fields=["lead", "-created_at"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.lead_id and self.organization_id != self.lead.organization_id:
            raise ValidationError({"organization": "Call organization must match the lead organization."})
        if self.telecaller_membership_id and self.telecaller_membership.organization_id != self.organization_id:
            raise ValidationError({"telecaller_membership": "Telecaller must belong to this organization."})

    def __str__(self):
        return f"{self.lead} - {self.get_outcome_display()}"
