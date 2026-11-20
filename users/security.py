import hashlib
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.authtoken.models import Token

from core.middleware.rate_limit import client_ip

from .models import DeveloperAccount, UserSecurityProfile, UserSession


class AccountLocked(APIException):
    status_code = 423
    default_code = "account_locked"

    def __init__(self, remaining_seconds):
        super().__init__({
            "detail": "Account is temporarily locked after repeated failed login attempts.",
            "remaining_seconds": max(1, int(remaining_seconds)),
        })


class InvalidCredentials(Exception):
    pass


def token_hash(token_key):
    return hashlib.sha256(token_key.encode("utf-8")).hexdigest()


def is_developer(user):
    return bool(user and user.is_authenticated and DeveloperAccount.objects.filter(user_id=user.pk).exists())


def normalize_phone(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("+"):
        return "+" + re.sub(r"\D", "", value)
    return re.sub(r"\D", "", value)


def resolve_user(identifier):
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    identifier = identifier.strip()
    user_model = get_user_model()
    user = user_model.objects.filter(email__iexact=identifier).first()
    if user:
        return user
    phone = normalize_phone(identifier)
    if not phone:
        return None
    profile = UserSecurityProfile.objects.select_related("user").filter(phone=phone).first()
    return profile.user if profile else None


def get_security_profile(user, *, lock=False):
    manager = UserSecurityProfile.objects
    if lock:
        manager = manager.select_for_update()
    profile, _ = manager.get_or_create(user=user)
    return profile


def authenticate_with_lockout(identifier, password):
    user = resolve_user(identifier)
    if user is None or not user.is_active:
        raise InvalidCredentials
    now = timezone.now()
    invalid_credentials = False
    remaining_seconds = None
    with transaction.atomic():
        profile = get_security_profile(user, lock=True)
        if profile.is_locked(now):
            raise AccountLocked((profile.locked_until - now).total_seconds())
        if not isinstance(password, str) or not user.check_password(password):
            profile.failed_attempts += 1
            if profile.failed_attempts >= 5:
                profile.locked_until = now + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
                profile.save(update_fields=("failed_attempts", "locked_until"))
                remaining_seconds = (profile.locked_until - now).total_seconds()
            else:
                profile.save(update_fields=("failed_attempts",))
                invalid_credentials = True
        else:
            profile.failed_attempts = 0
            profile.locked_until = None
            profile.last_login_at = now
            profile.save(update_fields=("failed_attempts", "locked_until", "last_login_at"))
    if remaining_seconds is not None:
        raise AccountLocked(remaining_seconds)
    if invalid_credentials:
        raise InvalidCredentials
    return user


def _raise_if_locked(user, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        profile = get_security_profile(user, lock=True)
        if profile.is_locked(now):
            raise AccountLocked((profile.locked_until - now).total_seconds())


def record_failed_otp_attempt(identifier):
    """Count an invalid OTP against the same account lockout state as passwords."""
    user = resolve_user(identifier)
    if user is None or not user.is_active:
        return

    now = timezone.now()
    with transaction.atomic():
        profile = get_security_profile(user, lock=True)
        if profile.is_locked(now):
            raise AccountLocked((profile.locked_until - now).total_seconds())
        profile.failed_attempts += 1
        if profile.failed_attempts >= 5:
            profile.locked_until = now + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
            profile.save(update_fields=("failed_attempts", "locked_until"))
            remaining_seconds = (profile.locked_until - now).total_seconds()
        else:
            profile.save(update_fields=("failed_attempts",))
            remaining_seconds = None
    if remaining_seconds is not None:
        raise AccountLocked(remaining_seconds)


def record_successful_otp_authentication(user):
    """Clear failed-login state after a valid OTP authenticates the account."""
    now = timezone.now()
    with transaction.atomic():
        profile = get_security_profile(user, lock=True)
        profile.failed_attempts = 0
        profile.locked_until = None
        profile.last_login_at = now
        profile.save(update_fields=("failed_attempts", "locked_until", "last_login_at"))


def validate_password_policy(password, user=None):
    try:
        validate_password(password, user)
    except ValidationError:
        raise
    if not isinstance(password, str) or len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password) or not re.search(r"[^A-Za-z\d]", password):
        raise ValidationError("Password must be at least 8 characters and contain a letter, a number, and a symbol.")


def issue_session(user, request):
    timeout_minutes = get_session_timeout_minutes(user)
    with transaction.atomic():
        token, _ = Token.objects.get_or_create(user=user)
        now = timezone.now()
        UserSession.objects.update_or_create(
            token_hash=token_hash(token.key),
            defaults={
                "user": user,
                "ip_address": client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
                "last_activity_at": now,
                "expires_at": now + timedelta(minutes=timeout_minutes),
                "revoked_at": None,
            },
        )
    return token


def get_session_timeout_minutes(user):
    from system_settings.services import get_user_session_timeout_minutes

    return get_user_session_timeout_minutes(user) or settings.AUTH_SESSION_TIMEOUT_MINUTES


def revoke_session_token(token_key):
    with transaction.atomic():
        now = timezone.now()
        UserSession.objects.filter(token_hash=token_hash(token_key), revoked_at__isnull=True).update(revoked_at=now)
        Token.objects.filter(key=token_key).delete()


def revoke_user_sessions(user):
    with transaction.atomic():
        now = timezone.now()
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
        Token.objects.filter(user=user).delete()
