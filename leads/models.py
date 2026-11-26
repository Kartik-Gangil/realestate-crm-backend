from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .constants import LEAD_STATUS_NEW
from .phone import normalize_phone


class LeadCodeSequence(models.Model):
    project = models.OneToOneField("inventory.Project", on_delete=models.CASCADE, related_name="lead_code_sequence")
    next_number = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class LeadHistory(models.Model):
    lead = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="history")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="lead_history")
    project = models.ForeignKey("inventory.Project", on_delete=models.CASCADE, related_name="lead_history")
    action = models.CharField(max_length=64)
    details = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_history_entries")
    created_at = models.DateTimeField(auto_now_add=True)


class LeadImportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="lead_import_batches")
    project = models.ForeignKey("inventory.Project", on_delete=models.CASCADE, related_name="lead_import_batches")
    file_name = models.CharField(max_length=255)
    upload = models.FileField(upload_to="lead_imports/%Y/%m/")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    current_chunk = models.PositiveIntegerField(default=0)
    error_report = models.FileField(upload_to="lead_import_errors/%Y/%m/", null=True, blank=True)
    error_rows = models.JSONField(default=list, blank=True)
    import_duplicates = models.BooleanField(default=False)
    task_id = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="lead_import_batches")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Lead(models.Model):

    class Source(models.TextChoices):
        FACEBOOK = "fb", "Facebook"
        INSTAGRAM = "ig", "Instagram"
        WEBSITE = "website", "Website"
        SITEVISIT = "site_visit", "Site Visit"
        OTHER = "other", "Other"
        WALKIN = "walk_in", "Walk-in"
        GOOGLE = "google", "Google"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="leads")
    project = models.ForeignKey("inventory.Project", on_delete=models.PROTECT, related_name="leads")
    lead_code = models.CharField(max_length=100, blank=True, default="")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20)
    alt_phone = models.CharField(max_length=20 , blank=True)
    address = models.CharField(max_length=200 , blank=True)
    # Lead sources are project-scoped Master Data (FR-P2-01 / FR-P4-02 / GNFR-09).
    # Keep the legacy code column for compatibility, but do not enforce a stale
    # application-level choice list before the project source is resolved.
    source = models.CharField(max_length=64, default=Source.WEBSITE)
    source_item = models.ForeignKey("system_settings.MasterData", null=True, blank=True, on_delete=models.PROTECT, related_name="lead_source_items")
    status = models.ForeignKey("system_settings.MasterData", null=True, blank=True, on_delete=models.PROTECT, related_name="lead_status_items")
    lifecycle_status = models.CharField(max_length=32, default="new", null=True, blank=True)
    score = models.PositiveIntegerField(null=True, blank=True)
    budget_range = models.CharField(max_length=120, blank=True, default="")
    preferred_location = models.CharField(max_length=200, blank=True, default="")
    external_source = models.CharField(max_length=64, blank=True, default="")
    external_id = models.CharField(max_length=255, blank=True, default="")
    assigned_membership = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_leads")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "source"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "lead_code"],
                condition=~models.Q(lead_code=""),
                name="leads_project_lead_code_unique",
            ),
            models.UniqueConstraint(
                fields=["project", "external_source", "external_id"],
                condition=~models.Q(external_id=""),
                name="leads_project_external_id_unique",
            ),
        ]

    @property
    def full_name(self):
        return " ".join(part for part in [self.first_name, self.last_name] if part)

    def clean(self):
        if self.assigned_membership_id and self.assigned_membership.organization_id != self.organization_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({"assigned_membership": "Assignee must belong to this organization."})

    def save(self, *args, **kwargs):
        if self.phone:
            normalized = normalize_phone(self.phone)
            if normalized is None:
                raise ValidationError({"phone": "Phone number cannot be normalized."})
            self.phone = normalized
        if self.alt_phone:
            normalized_alt = normalize_phone(self.alt_phone)
            if normalized_alt is None:
                raise ValidationError({"alt_phone": "Phone number cannot be normalized."})
            self.alt_phone = normalized_alt
        if self.project_id and not self.lead_code:
            from .codes import next_lead_code
            self.lead_code = next_lead_code(self.project)
        if self.project_id and self.source_item_id is None:
            from system_settings.models import MasterData
            self.source_item_id = MasterData.objects.filter(
                organization_id=self.organization_id,
                project_id=self.project_id,
                category__code="lead_source",
                code=self.source,
            ).values_list("id", flat=True).first()
        if self.project_id and self.status_id is None:
            from system_settings.models import MasterData
            self.status_id = MasterData.objects.filter(
                organization_id=self.organization_id,
                project_id=self.project_id,
                category__code="lead_stage",
                code=LEAD_STATUS_NEW,
                is_active=True,
            ).values_list("id", flat=True).first()
        if self.source_item_id:
            self.source = type(self).objects.filter(pk=self.pk).values_list("source", flat=True).first() or self.source
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


class ImmutableLeadHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Lead history rows are immutable and cannot be updated.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Lead history rows are immutable and cannot be deleted.")


class LeadAssignmentHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="assignment_history")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="lead_assignment_history")
    assigned_from = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_assignments_from")
    assigned_to = models.ForeignKey("organizations.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_assignments_to")
    reason = models.TextField()
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_assignment_actions")
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableLeadHistoryQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Lead assignment history rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Lead assignment history rows are immutable and cannot be deleted.")

    class Meta:
        ordering = ["created_at", "id"]


class LeadStatusHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="status_history")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="lead_status_history")
    old_status = models.CharField(max_length=32)
    new_status = models.CharField(max_length=32)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_status_actions")
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableLeadHistoryQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Lead status history rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Lead status history rows are immutable and cannot be deleted.")

    class Meta:
        ordering = ["created_at", "id"]


class LeadTag(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="tags")
    tag_name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tag_name", "id"]
        constraints = [models.UniqueConstraint(fields=["lead", "tag_name"], name="unique_lead_tag")]


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
    project = models.ForeignKey("inventory.Project", on_delete=models.PROTECT, related_name="site_visits")
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
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
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
            self.Status.RESCHEDULED: {self.Status.UPCOMING, self.Status.IN_PROGRESS, self.Status.COMPLETED, self.Status.CANCELLED, self.Status.NO_SHOW},
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
    reminder_sent = models.BooleanField(default=False, db_default=False)
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
