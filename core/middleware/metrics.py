import time

from django.urls import Resolver404, resolve

from core.metrics import record_request


def _route_pattern(request):
    try:
        match = resolve(request.path_info)
        route = getattr(match.route, "_route", None)
        if route:
            return f"/{route}".rstrip("/") or "/"
    except Resolver404:
        pass
    return request.path_info


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        try:
            response = self.get_response(request)
        except Exception:
            record_request(request.method, _route_pattern(request), 500, time.perf_counter() - started)
            raise
        record_request(request.method, _route_pattern(request), response.status_code, time.perf_counter() - started)
        return response

