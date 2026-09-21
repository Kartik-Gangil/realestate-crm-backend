from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer
from .models import UserSession, hash_auth_token


def _auth_response(user, created=False):
    token, _ = Token.objects.get_or_create(user=user)
    UserSession.objects.update_or_create(
        token_hash=hash_auth_token(token.key),
        defaults={
            "user": user,
            "ip_address": None,
            "user_agent": "",
            "expires_at": timezone.now() + timedelta(seconds=getattr(settings, "SESSION_COOKIE_AGE", 1209600)),
        },
    )
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return _auth_response(serializer.save(), created=True)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    serializer = LoginSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    response = _auth_response(serializer.validated_data["user"])
    token = response.data["token"]
    UserSession.objects.filter(token_hash=hash_auth_token(token)).update(
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    if request.auth:
        UserSession.objects.filter(token_hash=hash_auth_token(request.auth.key)).delete()
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
