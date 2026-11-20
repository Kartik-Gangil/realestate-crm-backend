from django.conf import settings
from django.core.cache import caches
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from rest_framework.permissions import AllowAny


PUBLIC_PATHS = ("/api/auth/", "/api/v1/auth/")


def client_ip(request):
    """Return the client address using the same trusted-proxy rule everywhere."""
    if settings.DJANGO_TRUST_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _is_public_auth_request(request):
    if not request.path_info.startswith(PUBLIC_PATHS):
        return False
    try:
        callback = resolve(request.path_info).func
    except Resolver404:
        return False
    view_class = getattr(callback, "cls", None)
    permission_classes = getattr(view_class, "permission_classes", ())
    return any(issubclass(permission_class, AllowAny) for permission_class in permission_classes)


def _is_exempt(path):
    return path in {"/healthz", "/readyz"} or path.startswith("/admin/") or not path.startswith("/api/")


class RateLimitMiddleware:
    """GNFR-14: fixed-window per-client-IP limits using process-local cache."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_exempt(request.path):
            return self.get_response(request)

        cache = caches["ratelimit"]
        is_public = _is_public_auth_request(request)
        limit = settings.RATE_LIMIT_PUBLIC_PER_MINUTE if is_public else settings.RATE_LIMIT_API_PER_MINUTE
        bucket = "public" if is_public else "api"
        key = f"crm-rate-limit:{bucket}:{client_ip(request)}"
        if not cache.add(key, 1, timeout=60):
            try:
                count = cache.incr(key)
            except ValueError:
                cache.add(key, 1, timeout=60)
                count = 1
        else:
            count = 1
        if count > limit:
            return JsonResponse(
                {"detail": "Too many requests. Try again later."},
                status=429,
                headers={"Retry-After": "60"},
            )
        return self.get_response(request)
