from core.audit_context import reset_current_request, set_current_request
from django.db import OperationalError, transaction
from django.http import JsonResponse


class AuditContextMiddleware:
    """Make the current request available to model audit signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_request(request)
        try:
            is_api_write = request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            if is_api_write:
                try:
                    with transaction.atomic():
                        response = self.get_response(request)
                        if getattr(response, "status_code", 200) >= 500:
                            transaction.set_rollback(True)
                        return response
                except OperationalError:
                    return JsonResponse({"detail": "The database is busy; please retry."}, status=503)
            return self.get_response(request)
        finally:
            reset_current_request(token)
