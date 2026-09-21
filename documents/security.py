import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _key():
    configured = getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "")
    if configured:
        try:
            key = base64.urlsafe_b64decode(configured.encode())
        except Exception as exc:
            raise ValueError("DOCUMENT_ENCRYPTION_KEY must be urlsafe-base64 encoded") from exc
        if len(key) != 32:
            raise ValueError("DOCUMENT_ENCRYPTION_KEY must decode to 32 bytes")
        return key
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()


def encrypt_bytes(value):
    nonce = os.urandom(12)
    return b"CRM-AES256-GCM\x01" + nonce + AESGCM(_key()).encrypt(nonce, value, None)


def decrypt_bytes(value):
    prefix = b"CRM-AES256-GCM\x01"
    if not value.startswith(prefix):
        return value
    nonce = value[len(prefix):len(prefix) + 12]
    return AESGCM(_key()).decrypt(nonce, value[len(prefix) + 12:], None)


def encrypt_text(value):
    return base64.urlsafe_b64encode(encrypt_bytes(value.encode())).decode()
