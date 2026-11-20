from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import UserSession
from .security import token_hash
from .security import get_session_timeout_minutes


class SessionTokenAuthentication(TokenAuthentication):
    """Token auth backed by a revocable, inactivity-expiring server session."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if not user.is_active:
            raise AuthenticationFailed("User account is inactive.")
        from organizations.services import is_platform_admin
        from organizations.models import OrganizationMembership
        if not is_platform_admin(user) and not OrganizationMembership.objects.filter(user=user, is_active=True).exists():
            from .security import revoke_user_sessions
            revoke_user_sessions(user)
            raise AuthenticationFailed("No active organization membership.")
        return user, token

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        now = timezone.now()
        session = UserSession.objects.filter(
            token_hash=token_hash(key), user=user, revoked_at__isnull=True
        ).first()
        if session is None:
            raise AuthenticationFailed("Invalid or expired session.")
        timeout_minutes = get_session_timeout_minutes(user)
        if session.expires_at <= now or session.last_activity_at + timedelta(minutes=timeout_minutes) <= now:
            session.revoked_at = now
            session.save(update_fields=("revoked_at",))
            raise AuthenticationFailed("Session expired.")
        session.last_activity_at = now
        session.expires_at = now + timedelta(minutes=timeout_minutes)
        session.save(update_fields=("last_activity_at", "expires_at"))
        return user, token
