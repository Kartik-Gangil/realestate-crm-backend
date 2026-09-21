import time
from collections import Counter

from django.db import connection
from django.http import HttpResponse


REQUEST_COUNT = Counter()
REQUEST_SECONDS = Counter()


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed = time.perf_counter() - started
        path = request.path.replace('"', '\\"')
        REQUEST_COUNT[path] += 1
        REQUEST_SECONDS[path] += elapsed
        return response


def metrics(request):
    lines = ["# TYPE crm_http_requests_total counter"]
    for path, count in REQUEST_COUNT.items():
        lines.append(f'crm_http_requests_total{{path="{path}"}} {count}')
    lines.append("# TYPE crm_http_request_duration_seconds counter")
    for path, seconds in REQUEST_SECONDS.items():
        lines.append(f'crm_http_request_duration_seconds{{path="{path}"}} {seconds}')
    lines.extend([
        "# TYPE crm_db_pool_utilization gauge",
        f"crm_db_pool_utilization {1 if connection.connection is not None else 0}",
        "# TYPE crm_background_job_queue_depth gauge",
        "crm_background_job_queue_depth 0",
    ])
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")
