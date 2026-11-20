from django.conf import settings
from django.db import models
from django.utils import timezone


class UserSecurityProfile(models.Model):
    """Security state that is intentionally separate from the auth user row."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_profile")
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    def is_locked(self, now=None):
        now = now or timezone.now()
        return bool(self.locked_until and self.locked_until > now)


class UserSession(models.Model):
    """Server-side lifecycle record for every DRF token session."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_sessions")
    token_hash = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=("user", "revoked_at")),
            models.Index(fields=("expires_at", "revoked_at")),
        ]


class DeveloperAccount(models.Model):
    """Server-managed marker for the highest platform account level."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="developer_account")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "Developer account"
