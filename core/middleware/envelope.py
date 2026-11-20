import json
import logging

from django.http import JsonResponse
from django.utils import timezone

from core.exceptions import is_database_busy_error
from core.metrics import record_database_busy

logger = logging.getLogger(__name__)


ERROR_CODES = {
    400: "validation_error",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "throttled",
    423: "account_locked",
    503: "database_busy",
    500: "server_error",
}

ERROR_MESSAGES = {
    400: "Request validation failed.",
    401: "Authentication is required.",
    403: "Permission denied.",
    404: "Resource not found.",
    405: "Method not allowed.",
    409: "The request conflicts with the current resource state.",
    429: "Too many requests.",
    503: "The database is busy. Please retry.",
    500: "An unexpected server error occurred.",
}


def _is_v1_path(path):
    return path.startswith("/api/v1/")


def _meta(request):
    underlying_request = getattr(request, "_request", request)
    return {
        "timestamp": timezone.now().isoformat(),
        "project_id": getattr(underlying_request, "_validated_project_id", None),
    }


def _response_data(response):
    if hasattr(response, "data"):
        return response.data
    content_type = response.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type == "application/json" and response.content:
        try:
            return json.loads(response.content)
        except (TypeError, ValueError):
            return None
    return None


def _is_standard_envelope(payload):
    return isinstance(payload, dict) and {"success", "data", "error"}.issubset(payload)


def _error_details(response, payload):
    if payload is not None:
        return payload
    return {"detail": response.reason_phrase}


def _error_message(status_code, payload):
    if isinstance(payload, dict) and payload.get("detail"):
        detail = payload["detail"]
        if isinstance(detail, list):
            return str(detail[0]) if detail else ERROR_MESSAGES.get(status_code, "Request failed.")
        return str(detail)
    return ERROR_MESSAGES.get(status_code, "Request failed.")


def _error_response(request, status_code, payload, *, retry_after=None):
    code = ERROR_CODES.get(status_code)
    if code is None:
        code = "client_error" if 400 <= status_code < 500 else "server_error"
    if isinstance(payload, dict) and payload.get("code") == "database_busy":
        code = "database_busy"
        status_code = 503
    message = ERROR_MESSAGES.get(status_code, "Request failed.") if status_code == 500 else _error_message(status_code, payload)
    body = {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": payload if payload is not None else {},
        },
        "meta": _meta(request),
    }
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return _render_response(body, status_code, headers, compat_data=payload)


def _render_response(body, status_code, headers=None, *, compat_data=None):
    return EnvelopeJsonResponse(
        body,
        status=status_code,
        headers=headers or {},
        compat_data=compat_data,
    )


class EnvelopeJsonResponse(JsonResponse):
    """temporary: response.data keeps the inner payload for legacy tests; remove at close-out (G-2)."""

    def __init__(self, data, *args, compat_data=None, **kwargs):
        self.data = data if compat_data is None else compat_data
        super().__init__(data, *args, **kwargs)


class ApiV1EnvelopeMiddleware:
    """GNFR-04: normalize only the versioned API response contract."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _is_v1_path(request.path):
            return self.get_response(request)
        try:
            response = self.get_response(request)
        except Exception as error:
            logger.error("Caught %s while handling %s", type(error).__name__, request.path)
            if is_database_busy_error(error):
                record_database_busy()
                return _error_response(request, 503, {"code": "database_busy"}, retry_after="1")
            return _error_response(request, 500, {})
        return self._wrap_response(request, response)

    def _wrap_response(self, request, response):
        payload = _response_data(response)
        if _is_standard_envelope(payload):
            body = dict(payload)
            body["meta"] = _meta(request)
            headers = {}
            if response.get("Retry-After"):
                headers["Retry-After"] = response["Retry-After"]
            return _render_response(
                body,
                200 if response.status_code == 204 else response.status_code,
                headers,
                compat_data=payload,
            )

        if response.status_code >= 400:
            retry_after = response.get("Retry-After")
            return _error_response(request, response.status_code, payload, retry_after=retry_after)

        if response.status_code < 400 and response.status_code != 204 and not _is_standard_envelope(payload) and response.get("Content-Type", "").split(";", 1)[0].lower() not in {"", "application/json"}:
            return response

        status_code = 200 if response.status_code == 204 else response.status_code
        body = {
            "success": True,
            "data": None if response.status_code == 204 else payload,
            "error": None,
            "meta": _meta(request),
        }
        return _render_response(body, status_code, compat_data=payload)
