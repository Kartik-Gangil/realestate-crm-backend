from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
import re
TAB_PERMISSIONS = (
    "dashboard", "leads", "assigned_leads", "follow_ups", "telecalling",
    "members", "site-visits", "plots", "payments", "registry", "loans",
    "employees", "documents", "expenses", "communications", "settings",
)


def default_tab_permissions():
    """Compatibility callable required by the historical tab migration."""
    return list(TAB_PERMISSIONS)


def normalize_mobile_number(value):
    """Return a canonical Indian mobile number or raise for invalid input."""
    if value is None:
        return ""
    compact = re.sub(r"\D", "", str(value).strip())
    if not compact:
        return ""
    if compact.startswith("0") and len(compact) == 11:
        compact = compact[1:]
    elif compact.startswith("91") and len(compact) == 12:
        compact = compact[2:]
    if len(compact) != 10 or compact[0] not in "6789":
        raise ValueError("Enter a valid Indian mobile number.")
    return f"+91{compact}"


class Organization(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    # Last telecaller used by the organization round-robin allocator.
    round_robin_cursor = models.PositiveBigIntegerField(null=True, blank=True)
    employee_sequence = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_organizations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Organization admin"
        MANAGER = "manager", "Manager"
        TELECALLER = "telecaller", "Telecaller"
        HR_ADMIN = "hr-admin", "HR Admin"
        ACCOUNTS = "accounts", "Accounts"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    # Deprecated compatibility display value. Authorization uses organization_role.
    organization_role = models.ForeignKey("OrganizationRole", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="memberships")
    is_active = models.BooleanField(default=True)

    # Employee data is organization-specific, so it belongs on the membership
    # rather than the globally shared Django user.
    employee_id = models.CharField(max_length=32, null=True, blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    profile_photo = models.FileField(upload_to="employee_profiles/%Y/%m/", null=True, blank=True)
    mobile_number = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    department = models.ForeignKey(
        "Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    designation = models.CharField(max_length=150, blank=True)
    reporting_manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )
    date_of_joining = models.DateField(null=True, blank=True)
    employment_type = models.CharField(max_length=50, blank=True)
    salary = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    work_location = models.CharField(max_length=150, blank=True)
    shift_start_time = models.TimeField(null=True, blank=True)
    shift_end_time = models.TimeField(null=True, blank=True)

    class AccessScope(models.TextChoices):
        ALL = "all", "All Data"
        OWN = "own", "Own Data"
        DEPARTMENT = "department", "Department Data"
        CUSTOM = "custom", "Custom Scope"

    access_scope = models.CharField(max_length=20, choices=AccessScope.choices, default=AccessScope.OWN)
    custom_scope_memberships = models.ManyToManyField("self", blank=True, symmetrical=False, related_name="included_in_custom_scopes")
    custom_scope_departments = models.ManyToManyField("Department", blank=True, related_name="included_in_custom_scopes")

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_organization_membership"),
            models.UniqueConstraint(
                fields=["organization", "employee_id"],
                condition=Q(employee_id__isnull=False),
                name="unique_organization_employee_id",
            ),
            models.UniqueConstraint(
                fields=["organization", "mobile_number"],
                condition=~Q(mobile_number=""),
                name="unique_organization_mobile_number",
            ),
        ]
        indexes = [models.Index(fields=["organization", "role", "is_active"])]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    def clean(self):
        super().clean()
        errors = {}
        try:
            self.mobile_number = normalize_mobile_number(self.mobile_number)
        except ValueError as error:
            errors["mobile_number"] = str(error)
        if self.mobile_number and self.organization_id:
            duplicate = OrganizationMembership.objects.filter(
                organization_id=self.organization_id,
                mobile_number=self.mobile_number,
            ).exclude(pk=self.pk).exists()
            if duplicate:
                errors["mobile_number"] = "An employee with this mobile number already exists in this organization."
        if self.department_id and self.department.organization_id != self.organization_id:
            errors["department"] = "Department must belong to this organization."
        if self.reporting_manager_id:
            if self.reporting_manager.organization_id != self.organization_id:
                errors["reporting_manager"] = "Reporting manager must belong to this organization."
            elif self.pk and self.reporting_manager_id == self.pk:
                errors["reporting_manager"] = "An employee cannot report to themselves."
        if self.salary is not None and self.salary < 0:
            errors["salary"] = "Salary cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.mobile_number = normalize_mobile_number(self.mobile_number)
        # Legacy role is compatibility data. New memberships get a canonical role.
        if self.organization_id and not self.organization_role_id:
            role = OrganizationRole.objects.filter(organization_id=self.organization_id, code=self.role).first()
            if role is None:
                from .services import ensure_default_roles
                role = ensure_default_roles(self.organization).get(self.role)
            if role:
                self.organization_role = role
        return super().save(*args, **kwargs)


class Department(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_organization_department_name")]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class Permission(models.Model):
    """Small, reusable permission catalogue; roles select from this catalogue."""
    SCOPE_CHOICES = (("organization", "Organization"), ("project", "Project"))

    module = models.CharField(max_length=32)
    action = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default="project")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["module", "action"], name="organization_permission_unique")]
        ordering = ["module", "action"]

    @property
    def code(self):
        return f"{self.module}.{self.action}"

    def __str__(self):
        return self.code


class OrganizationRole(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50)
    description = models.TextField(blank=True, default="")
    permissions = models.ManyToManyField(Permission, blank=True, related_name="organization_roles")
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="organization_role_name_unique"), models.UniqueConstraint(fields=["organization", "code"], name="organization_role_code_unique")]

    def __str__(self):
        return f"{self.organization}: {self.name}"


class ProjectAssignment(models.Model):
    """The role a membership holds inside one project."""

    membership = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="project_assignments")
    project = models.ForeignKey("inventory.Project", on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(OrganizationRole, on_delete=models.PROTECT, related_name="project_assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_project_assignments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("membership", "project"), name="unique_project_membership_assignment")]

    def clean(self):
        super().clean()
        errors = {}
        if self.membership_id and self.project_id and self.membership.organization_id != self.project.organization_id:
            errors["project"] = "Project must belong to the membership organization."
        if self.role_id and self.membership_id and self.role.organization_id != self.membership.organization_id:
            errors["role"] = "Role must belong to the membership organization."
        if errors:
            raise ValidationError(errors)


class OrganizationHoliday(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="holidays")
    name = models.CharField(max_length=150)
    holiday_date = models.DateField()
    source = models.CharField(max_length=32, default="custom")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["holiday_date", "name"]
        constraints = [models.UniqueConstraint(fields=["organization", "holiday_date"], name="organization_holiday_date_unique")]


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        INCOMPLETE = "incomplete", "Incomplete"
        ABSENT = "absent", "Absent"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="attendance_records")
    employee = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="attendance_records")
    attendance_date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    total_hours = models.DurationField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INCOMPLETE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attendance_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["employee", "attendance_date"], name="employee_daily_attendance_unique")]
        indexes = [models.Index(fields=["organization", "attendance_date", "status"])]

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if self.check_in and self.check_out and self.check_out < self.check_in:
            errors["check_out"] = "Check-out cannot precede check-in."
        if errors:
            raise ValidationError(errors)


class LeaveRequest(models.Model):
    class LeaveType(models.TextChoices):
        CASUAL = "casual", "Casual Leave"
        SICK = "sick", "Sick Leave"
        PAID = "paid", "Paid Leave"
        EARNED = "earned", "Earned Leave (legacy)"
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="leave_requests")
    employee = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.CharField(max_length=16, choices=LeaveType.choices)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.PositiveIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_leave_requests")
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "status", "from_date"])]

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if self.to_date and self.from_date and self.to_date < self.from_date:
            errors["to_date"] = "To date cannot precede from date."
        if errors:
            raise ValidationError(errors)


class LeaveBalance(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="leave_balances")
    employee = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="leave_balances")
    leave_type = models.CharField(max_length=16)
    year = models.PositiveSmallIntegerField()
    allocated_days = models.PositiveSmallIntegerField(default=0)
    used_days = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year", "leave_type", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "leave_type", "year"],
                name="employee_leave_balance_year_type_unique",
            ),
        ]

    @property
    def remaining_days(self):
        return max(self.allocated_days - self.used_days, 0)

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if self.used_days > self.allocated_days:
            errors["used_days"] = "Used leave days cannot exceed the allocated balance."
        if errors:
            raise ValidationError(errors)


class PerformanceReview(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="performance_reviews")
    employee = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="performance_reviews")
    quarter = models.CharField(max_length=7)
    rating = models.PositiveSmallIntegerField()
    comments = models.TextField(blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performance_reviews_written",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-quarter", "-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "quarter"],
                name="employee_performance_review_quarter_unique",
            ),
        ]

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.organization_id != self.organization_id:
            errors["employee"] = "Employee must belong to this organization."
        if not (1 <= self.rating <= 5):
            errors["rating"] = "Rating must be between 1 and 5."
        if not __import__("re").fullmatch(r"\d{4}-Q[1-4]", self.quarter or ""):
            errors["quarter"] = "Quarter must use YYYY-Qn format."
        if errors:
            raise ValidationError(errors)


class OrganizationActivity(models.Model):
    """Append-only audit records for organization-scoped employee mutations."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="activities")
    employee = models.ForeignKey(OrganizationMembership, on_delete=models.CASCADE, related_name="activity_history")
    action = models.CharField(max_length=64)
    module = models.CharField(max_length=64, default="employees")
    details = models.JSONField(default=dict, blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="organization_activities")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "employee", "-created_at"])]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Activity records are immutable.")
        return super().save(*args, **kwargs)


class PlatformOrganizationAccess(models.Model):
    """Explicit organization access for a platform admin (not a tenant membership)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="platform_accesses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_organization_accesses")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="granted_platform_accesses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_platform_organization_access")]

    def clean(self):
        from users.security import is_developer
        if not is_developer(self.user) and not self.user.groups.filter(name="Platform Admin").exists() and not self.user.is_superuser:
            raise ValidationError({"user": "Only a platform admin or superadmin can receive platform access."})
