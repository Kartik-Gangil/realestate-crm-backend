from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.response import Response

from core.endpoint import crm_endpoint


from .otp import (
    FirebaseOtpStorageUnavailable,
    OtpDeliveryUnavailable,
    OtpInvalid,
    OtpRateLimited,
    request_email_otp,
    verify_email_otp,
)
from .serializers import LoginSerializer, OtpRequestSerializer, UserSerializer
from .security import (
    AccountLocked,
    _raise_if_locked,
    issue_session,
    record_failed_otp_attempt,
    record_successful_otp_authentication,
    resolve_user,
    revoke_session_token,
    revoke_user_sessions,
    get_session_timeout_minutes,
    validate_password_policy,
)


class PasswordResetDeliveryError(Exception):
    """Raised when a password-reset email cannot be delivered."""


def send_password_reset_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"{settings.PASSWORD_RESET_FRONTEND_URL}?uid={uid}&token={token}"
    try:
        sent = send_mail(
            "Reset your password",
            f"Use this link to reset your password: {reset_url}",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception as error:
        raise PasswordResetDeliveryError(
            "Password reset email could not be sent. Configure email delivery and try again."
        ) from error
    if sent != 1:
        raise PasswordResetDeliveryError(
            "Password reset email could not be sent. Configure email delivery and try again."
        )


def _auth_response(user, request, created=False):
    token = issue_session(user, request)
    return Response({"token": token.key, "user": {**UserSerializer(user).data, "session_timeout_minutes": get_session_timeout_minutes(user)}}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@crm_endpoint(["POST"], scope="public")
def login(request):
    if request.data.get("mode") == "otp":
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            return Response({"detail": "If an active account uses this email address, an OTP has been sent."})
        try:
            request_email_otp(user)
        except OtpRateLimited as error:
            return Response(
                {"detail": "Too many OTP requests. Try again later.", "retry_after_seconds": error.retry_after_seconds},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except (FirebaseOtpStorageUnavailable, OtpDeliveryUnavailable):
            return Response({"detail": "OTP delivery is temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"detail": "If an active account uses this email address, an OTP has been sent."})

    serializer = LoginSerializer(data=request.data, context={"request": request})
    try:
        serializer.is_valid(raise_exception=True)
    except AccountLocked as error:
        return Response(
            {
                "detail": str(error.detail.get("detail", "Account temporarily locked.")),
                "remaining_seconds": int(error.detail.get("remaining_seconds", 1)),
            },
            status=error.status_code,
        )
    return _auth_response(serializer.validated_data["user"], request)


@crm_endpoint(["POST"], scope="public")
def verify_otp(request):
    identifier = request.data.get("identifier")
    otp = request.data.get("otp")
    if not identifier or not otp:
        return Response({"detail": "identifier and otp are required."}, status=status.HTTP_400_BAD_REQUEST)
    otp_user = resolve_user(identifier)
    if otp_user is not None and otp_user.is_active:
        try:
            _raise_if_locked(otp_user)
        except AccountLocked as error:
            return Response(
                {
                    "detail": str(error.detail.get("detail", "Account temporarily locked.")),
                    "remaining_seconds": int(error.detail.get("remaining_seconds", 1)),
                },
                status=error.status_code,
            )
    try:
        user = verify_email_otp(identifier, otp)
    except OtpInvalid:
        try:
            record_failed_otp_attempt(identifier)
        except AccountLocked as error:
            return Response(
                {
                    "detail": str(error.detail.get("detail", "Account temporarily locked.")),
                    "remaining_seconds": int(error.detail.get("remaining_seconds", 1)),
                },
                status=error.status_code,
            )
        return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)
    except FirebaseOtpStorageUnavailable:
        return Response({"detail": "OTP verification is temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    record_successful_otp_authentication(user)
    return _auth_response(user, request)


@crm_endpoint(["POST"], scope="user")
def logout(request):
    if request.auth:
        revoke_session_token(request.auth.key)
    return Response(status=status.HTTP_204_NO_CONTENT)


@crm_endpoint(["GET"], scope="user")
def me(request):
    return Response({**UserSerializer(request.user).data, "session_timeout_minutes": get_session_timeout_minutes(request.user)})


@crm_endpoint(["POST"], scope="public")
def forgot_password(request):
    """Send a time-limited reset link without revealing whether an account exists."""
    email = str(request.data.get("email", "")).strip().lower()
    try:
        from django.core.validators import validate_email

        validate_email(email)
    except ValidationError:
        return Response({"email": ["Enter a valid email address."]}, status=status.HTTP_400_BAD_REQUEST)
    if email:
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user:
            try:
                send_password_reset_email(user)
            except PasswordResetDeliveryError:
                return Response(
                    {
                        "code": "email_not_configured",
                        "detail": "Password reset email could not be sent. Configure email delivery and try again.",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
    return Response({"detail": "If an active account uses this email address, a password-reset link has been sent."})


@crm_endpoint(["POST"], scope="public")
def reset_password(request):
    uid = request.data.get("uid")
    token = request.data.get("token")
    new_password = request.data.get("new_password")
    if not uid or not token or not new_password:
        return Response({"detail": "uid, token, and new_password are required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = get_user_model().objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return Response({"token": ["This password-reset link is invalid or has expired."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password_policy(new_password, user)
    except ValidationError as error:
        return Response({"new_password": list(error.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_user_sessions(user)
    return Response({"detail": "Password has been reset."})


@crm_endpoint(["POST"], scope="user")
def change_password(request):
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not isinstance(old_password, str) or not request.user.check_password(old_password):
        return Response({"old_password": ["Current password is incorrect."]}, status=status.HTTP_400_BAD_REQUEST)
    if not new_password:
        return Response({"new_password": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password_policy(new_password, request.user)
    except ValidationError as error:
        return Response({"new_password": list(error.messages)}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    revoke_user_sessions(request.user)
    return Response({"detail": "Password has been changed."})
