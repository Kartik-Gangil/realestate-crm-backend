from django.db import connection
from django.core.cache import cache
from django.http import JsonResponse
from core.endpoint import public_endpoint


@public_endpoint
def healthz(request):
    """Liveness probe for FR-P0-05."""
    return JsonResponse({"status": "ok"})


@public_endpoint
def readyz(request):
    """Readiness probe for FR-P0-05, including database and cache connectivity."""
    database_status = "ok"
    cache_status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        database_status = "error"
    try:
        cache.get("__readyz_probe__")
    except Exception:
        cache_status = "error"
    status = 200 if database_status == cache_status == "ok" else 503
    return JsonResponse({"database": database_status, "cache": cache_status}, status=status)
