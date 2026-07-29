from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
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

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_organization_membership")]
        indexes = [models.Index(fields=["organization", "role", "is_active"])]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"


class PlatformOrganizationAccess(models.Model):
    """Explicit organization access for a platform admin (not a tenant membership)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="platform_accesses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="platform_organization_accesses")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="granted_platform_accesses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_platform_organization_access")]

    def clean(self):
        if not self.user.groups.filter(name="Platform Admin").exists() and not self.user.is_superuser:
            raise ValidationError({"user": "Only a platform admin or superadmin can receive platform access."})