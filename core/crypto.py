"""AES-256-GCM for stored files (GNFR-08, Appendix G-4). Never logs or echoes key material."""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

MAGIC = b"CRMENC1"
NONCE_BYTES = 12
TAG_BYTES = 16
OVERHEAD = len(MAGIC) + NONCE_BYTES + TAG_BYTES


class FileIntegrityError(Exception):
    """A stored file isn't CRM-encrypted, was changed, or used another key."""


def decode_file_key(value):
    try:
        key = base64.b64decode(value, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, TypeError):
        key = b""
    if len(key) != 32:
        raise ImproperlyConfigured("FILE_ENCRYPTION_KEY must be the URL-safe base64 encoding of exactly 32 bytes.")
    return key


def current_file_key():
    value = getattr(settings, "FILE_ENCRYPTION_KEY", "")
    if not value:
        raise ImproperlyConfigured("FILE_ENCRYPTION_KEY is not set, so stored files cannot be written or read.")
    return decode_file_key(value)


def encrypt_bytes(plaintext):
    nonce = os.urandom(NONCE_BYTES)
    return MAGIC + nonce + AESGCM(current_file_key()).encrypt(nonce, plaintext, MAGIC)


def decrypt_bytes(blob):
    if len(blob) < OVERHEAD or not blob.startswith(MAGIC):
        raise FileIntegrityError("The stored file is not encrypted, or it is damaged.")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    ciphertext = blob[len(MAGIC) + NONCE_BYTES:]
    try:
        return AESGCM(current_file_key()).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as error:
        raise FileIntegrityError("The stored file failed its integrity check.") from error
