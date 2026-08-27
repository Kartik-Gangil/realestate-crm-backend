import json
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken
from rest_framework.exceptions import ValidationError


def _fernet():
    if not settings.INTEGRATION_ENCRYPTION_KEY:
        raise ValidationError({"detail": "Integration secret storage is unavailable because INTEGRATION_ENCRYPTION_KEY is not configured."})
    try:
        return Fernet(settings.INTEGRATION_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as error:
        raise ValidationError({"detail": "Integration secret storage is unavailable due to an invalid encryption key."}) from error


def encrypt_secret(value):
    return _fernet().encrypt(json.dumps(value).encode()).decode()


def decrypt_secret(value):
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValidationError({"detail": "Stored integration secret cannot be decrypted."}) from error
