import hashlib

from django.conf import settings
from django.db import models


def hash_auth_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UserSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_sessions",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_sessions"
        indexes = [
            models.Index(fields=["user", "expires_at"]),
        ]
