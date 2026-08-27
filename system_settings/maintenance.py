from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.core.files.storage import default_storage


def clear_system_cache():
    if not hasattr(cache, "clear"):
        return "unsupported"
    cache.clear()
    return "completed"


def rebuild_search_index():
    return "unsupported"


def health_check():
    checks = {}
    try:
        with connection.cursor() as cursor: cursor.execute("SELECT 1")
        checks["database"] = "healthy"
    except Exception: checks["database"] = "unhealthy"
    try:
        default_storage.exists("")
        checks["storage"] = "healthy"
    except Exception: checks["storage"] = "unhealthy"
    checks["cache"] = "healthy" if hasattr(cache, "set") else "unsupported"
    try:
        executor = MigrationExecutor(connection)
        checks["migrations"] = "healthy" if not executor.migration_plan(executor.loader.graph.leaf_nodes()) else "pending"
    except Exception: checks["migrations"] = "unhealthy"
    return {"status": "healthy" if all(v in {"healthy", "unsupported"} for v in checks.values()) else "degraded", "checks": checks}
