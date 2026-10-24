from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


from .otp import (
    FirebaseOtpStorageUnavailable,
    OtpDeliveryUnavailable,
    OtpInvalid,
    OtpRateLimited,
    request_email_otp,
    verify_email_otp,
)
from .serializers import LoginSerializer, OtpRequestSerializer, RegisterSerializer, UserSerializer


def _auth_response(user, created=False):
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _auth_response(serializer.save(), created=True)


@api_view(["POST"])
@permission_classes([AllowAny])
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
    serializer.is_valid(raise_exception=True)
    return _auth_response(serializer.validated_data["user"])


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_otp(request):
    identifier = request.data.get("identifier")
    otp = request.data.get("otp")
    if not identifier or not otp:
        return Response({"detail": "identifier and otp are required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        user = verify_email_otp(identifier, otp)
    except OtpInvalid:
        return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)
    except FirebaseOtpStorageUnavailable:
        return Response({"detail": "OTP verification is temporarily unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return _auth_response(user)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    if request.auth:
        request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_password(request):
    """Send a time-limited reset link without revealing whether an account exists."""
    email = str(request.data.get("email", "")).strip().lower()
    if email:
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.PASSWORD_RESET_FRONTEND_URL}?uid={uid}&token={token}"
            send_mail(
                "Reset your password",
                f"Use this link to reset your password: {reset_url}",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
    return Response({"detail": "If an active account uses this email address, a password-reset link has been sent."})


@api_view(["POST"])
@permission_classes([AllowAny])
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
        validate_password(new_password, user)
    except ValidationError as error:
        return Response({"new_password": list(error.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return Response({"detail": "Password has been reset."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not isinstance(old_password, str) or not request.user.check_password(old_password):
        return Response({"old_password": ["Current password is incorrect."]}, status=status.HTTP_400_BAD_REQUEST)
    if not new_password:
        return Response({"new_password": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password(new_password, request.user)
    except ValidationError as error:
        return Response({"new_password": list(error.messages)}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    update_session_auth_hash(request, request.user)
    return Response({"detail": "Password has been changed."})
