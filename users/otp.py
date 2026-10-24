"""Email OTP delivery and verification for FR-P1-01."""

import re
import secrets
import time
from urllib.parse import urlparse

import firebase_admin
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from firebase_admin import credentials, db


OTP_TTL_SECONDS = 5 * 60
OTP_RATE_LIMIT_SECONDS = 10 * 60
OTP_RATE_LIMIT_COUNT = 3
OTP_PATTERN = re.compile(r"^\d{6}$")


class OtpInvalid(Exception):
    """The OTP is missing, invalid, expired, or already consumed."""


class OtpRateLimited(Exception):
    def __init__(self, retry_after_seconds):
        super().__init__("Too many OTP requests.")
        self.retry_after_seconds = retry_after_seconds


class FirebaseOtpStorageUnavailable(Exception):
    """Firebase Realtime Database could not be reached or configured."""


class OtpDeliveryUnavailable(Exception):
    """The configured SMTP service could not deliver the OTP."""


def _firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        database_url = settings.FIREBASE_DATABASE_URL.strip()
        database_host = urlparse(database_url).hostname
        required = {
            "type": "service_account",
            "project_id": settings.FIREBASE_PROJECT_ID,
            "client_email": settings.FIREBASE_CLIENT_EMAIL,
            "private_key": settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        if (
            not all(required.values())
            or not database_url
            or database_host == "console.firebase.google.com"
        ):
            raise FirebaseOtpStorageUnavailable("Firebase OTP storage is not configured.")
        try:
            certificate = credentials.Certificate(required)
            return firebase_admin.initialize_app(certificate, {"databaseURL": database_url})
        except Exception as error:
            raise FirebaseOtpStorageUnavailable("Firebase OTP storage is unavailable.") from error


def _otp_reference(user_id):
    try:
        return db.reference(f"auth/otp/{user_id}", app=_firebase_app())
    except FirebaseOtpStorageUnavailable:
        raise
    except Exception as error:
        raise FirebaseOtpStorageUnavailable("Firebase OTP storage is unavailable.") from error


def _new_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def request_email_otp(user):
    now = int(time.time())
    reference = _otp_reference(user.pk)
    try:
        otp = _new_otp()
        def issue(current):
            if not isinstance(current, dict):
                current = {}
            window_started_at = int(current.get("window_started_at", now))
            request_count = int(current.get("request_count", 0))
            if now - window_started_at < OTP_RATE_LIMIT_SECONDS and request_count >= OTP_RATE_LIMIT_COUNT:
                raise OtpRateLimited(OTP_RATE_LIMIT_SECONDS - (now - window_started_at))
            if now - window_started_at >= OTP_RATE_LIMIT_SECONDS:
                window_started_at = now
                request_count = 0
            return {
                "otp_hash": make_password(otp),
                "expires_at": now + OTP_TTL_SECONDS,
                "attempts": 0,
                "used": False,
                "created_at": now,
                "window_started_at": window_started_at,
                "request_count": request_count + 1,
            }

        payload = reference.transaction(issue)
        try:
            sent = send_mail(
                "Your Shriji CRM login OTP",
                f"Your login OTP is {otp}. It expires in 5 minutes.",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        except Exception as error:
            try:
                reference.delete()
            except Exception:
                pass
            raise OtpDeliveryUnavailable("The OTP email could not be sent.") from error
        if sent != 1:
            try:
                reference.delete()
            except Exception:
                pass
            raise OtpDeliveryUnavailable("The OTP email could not be sent.")
        return payload["expires_at"]
    except (OtpRateLimited, OtpDeliveryUnavailable, FirebaseOtpStorageUnavailable):
        raise
    except Exception as error:
        raise FirebaseOtpStorageUnavailable("Firebase OTP storage is unavailable.") from error


def verify_email_otp(identifier, otp):
    if not isinstance(identifier, str) or not isinstance(otp, str) or not OTP_PATTERN.fullmatch(otp):
        raise OtpInvalid

    user_model = get_user_model()
    user = user_model.objects.filter(email__iexact=identifier.strip(), is_active=True).first()
    if user is None:
        raise OtpInvalid

    reference = _otp_reference(user.pk)
    state = {"success": False}
    now = int(time.time())

    def consume(current):
        if not isinstance(current, dict) or not current or current.get("used"):
            state["error"] = "invalid"
            return current
        if int(current.get("expires_at", 0)) <= now:
            current["used"] = True
            current["used_at"] = now
            state["error"] = "expired"
            return current
        if not check_password(otp, str(current.get("otp_hash", ""))):
            current["attempts"] = int(current.get("attempts", 0)) + 1
            state["error"] = "invalid"
            return current
        current["used"] = True
        current["used_at"] = now
        state["success"] = True
        return current

    try:
        reference.transaction(consume)
    except Exception as error:
        raise FirebaseOtpStorageUnavailable("Firebase OTP storage is unavailable.") from error
    if not state["success"]:
        raise OtpInvalid
    return user
