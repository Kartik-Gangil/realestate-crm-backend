import threading
from collections import defaultdict
from pathlib import Path

from django.db import connection


_lock = threading.Lock()
_request_counts = defaultdict(int)
_latency_counts = defaultdict(lambda: [0, 0.0])
_database_busy_count = 0


def record_request(method, route, status_code, duration_seconds):
    key = (method, route, str(status_code))
    with _lock:
        _request_counts[key] += 1
        latency = _latency_counts[(method, route)]
        latency[0] += 1
        latency[1] += duration_seconds


def record_database_busy():
    global _database_busy_count
    with _lock:
        _database_busy_count += 1


def _escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _database_sizes():
    if connection.vendor != "sqlite":
        return None, None
    name = connection.settings_dict.get("NAME")
    if not name or name == ":memory:":
        return 0, 0
    database = Path(name)
    wal = Path(f"{name}-wal")
    return database.stat().st_size if database.is_file() else 0, wal.stat().st_size if wal.is_file() else 0


def _postgres_connection_count():
    if connection.vendor != "postgresql":
        return 0
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity")
            return int(cursor.fetchone()[0])
    except Exception:
        return 0


def prometheus_text():
    lines = [
        "# HELP crm_http_requests_total HTTP requests by method, route and status.",
        "# TYPE crm_http_requests_total counter",
    ]
    with _lock:
        counts = dict(_request_counts)
        latencies = {key: tuple(value) for key, value in _latency_counts.items()}
        database_busy = _database_busy_count
    for (method, route, status_code), count in sorted(counts.items()):
        labels = f'method="{_escape(method)}",route="{_escape(route)}",status="{_escape(status_code)}"'
        lines.append(f"crm_http_requests_total{{{labels}}} {count}")
    lines.extend([
        "# HELP crm_http_request_latency_seconds HTTP request latency.",
        "# TYPE crm_http_request_latency_seconds summary",
    ])
    for (method, route), (count, total) in sorted(latencies.items()):
        labels = f'method="{_escape(method)}",route="{_escape(route)}"'
        lines.append(f"crm_http_request_latency_seconds_count{{{labels}}} {count}")
        lines.append(f"crm_http_request_latency_seconds_sum{{{labels}}} {total:.6f}")
    lines.extend([
        "# HELP crm_database_busy_total Database lock-timeout responses.",
        "# TYPE crm_database_busy_total counter",
        f"crm_database_busy_total {database_busy}",
        "# HELP crm_task_queue_depth Background task queue depth by status.",
        "# TYPE crm_task_queue_depth gauge",
    ])
    try:
        from .models import TaskRecord
        for status in TaskRecord.Status.values:
            lines.append(f'crm_task_queue_depth{{status="{status}"}} {TaskRecord.objects.filter(status=status).count()}')
    except Exception:
        pass
    database_size, wal_size = _database_sizes()
    if database_size is not None:
        lines.extend([
            "# TYPE crm_sqlite_database_size_bytes gauge",
            f"crm_sqlite_database_size_bytes {database_size}",
            "# TYPE crm_sqlite_wal_size_bytes gauge",
            f"crm_sqlite_wal_size_bytes {wal_size}",
        ])
    lines.extend([
        "# TYPE crm_postgresql_connections gauge",
        f"crm_postgresql_connections {_postgres_connection_count()}",
    ])
    return "\n".join(lines) + "\n"

