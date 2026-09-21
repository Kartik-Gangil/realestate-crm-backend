import hashlib
import math
import time

from django.core.cache import cache
from rest_framework.exceptions import APIException


LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
LOGIN_FAILURE_CACHE_PREFIX = "users:login-failures:"


class AccountLocked(APIException):
    status_code = 423
    default_code = "account_locked"

    def __init__(self, remaining_seconds):
        super().__init__(f"Account is locked. Try again in {remaining_seconds} seconds.")


def _failure_cache_key(email):
    digest = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    return f"{LOGIN_FAILURE_CACHE_PREFIX}{digest}"


def locked_account_remaining(email):
    state = cache.get(_failure_cache_key(email))
    if not state or not state.get("locked_until"):
        return 0
    remaining = math.ceil(state["locked_until"] - time.time())
    if remaining <= 0:
        cache.delete(_failure_cache_key(email))
        return 0
    return remaining


def record_failed_login(email):
    key = _failure_cache_key(email)
    state = cache.get(key) or {"failed_attempts": 0, "locked_until": None}
    state["failed_attempts"] += 1
    if state["failed_attempts"] >= LOGIN_FAILURE_LIMIT:
        state["locked_until"] = time.time() + LOGIN_LOCKOUT_SECONDS
    cache.set(key, state, timeout=LOGIN_LOCKOUT_SECONDS)
    return locked_account_remaining(email)


def clear_failed_logins(email):
    cache.delete(_failure_cache_key(email))
