from django.db import OperationalError
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _has_postgres_lock_code(error):
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "pgcode", None) == "55P03":
            return True
        current = current.__cause__ or current.__context__
    return False


def is_database_busy_error(error):
    if not isinstance(error, OperationalError):
        return False
    message = str(error).lower()
    if any(marker in message for marker in ("database is locked", "database table is locked", "database schema is locked")):
        return True
    return _has_postgres_lock_code(error)


def database_exception_handler(exc, context):
    if is_database_busy_error(exc):
        return Response({"code": "database_busy"}, status=503, headers={"Retry-After": "1"})
    return exception_handler(exc, context)
