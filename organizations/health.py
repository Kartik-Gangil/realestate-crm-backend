from django.db import connection
from django.http import JsonResponse
from django.utils import timezone


def _payload(*, success, data, error):
    return {
        "success": success,
        "data": data,
        "error": error,
        "meta": {"timestamp": timezone.now().isoformat(), "project_id": None},
    }


def healthz(_request):
    """FR-P0-05 liveness: proves the application process can answer HTTP."""
    return JsonResponse(_payload(success=True, data={"status": "ok"}, error=None))


def readyz(_request):
    """FR-P0-05 readiness: fail traffic admission when the database is unavailable."""
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse(
            _payload(
                success=False,
                data=None,
                error={"code": "service_not_ready", "message": "Database is unavailable."},
            ),
            status=503,
        )
    return JsonResponse(_payload(success=True, data={"status": "ready"}, error=None))
