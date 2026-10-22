from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Liveness probe for FR-P0-05."""
    return JsonResponse({"status": "ok"})


def readyz(request):
    """Readiness probe for FR-P0-05, including database connectivity."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unready"}, status=503)
    return JsonResponse({"status": "ready"})
