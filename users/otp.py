import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache


OTP_TTL_SECONDS = 300
OTP_CACHE_KEY_PREFIX = "users:otp:"


def _otp_cache_key(account_key):
    return f"{OTP_CACHE_KEY_PREFIX}{account_key}"


def _hash_otp(account_key, otp):
    value = f"{account_key}:{otp}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), value, hashlib.sha256).hexdigest()


def store_otp(account_key, otp):
    """Store only a keyed hash of an OTP and expire it after five minutes."""
    cache.set(
        _otp_cache_key(account_key),
        _hash_otp(account_key, otp),
        timeout=OTP_TTL_SECONDS,
    )


def verify_otp(account_key, otp):
    """Validate and consume an OTP; expired or invalid values fail closed."""
    key = _otp_cache_key(account_key)
    stored_hash = cache.get(key)
    if not stored_hash:
        return False
    if not hmac.compare_digest(stored_hash, _hash_otp(account_key, otp)):
        return False
    cache.delete(key)
    return True
