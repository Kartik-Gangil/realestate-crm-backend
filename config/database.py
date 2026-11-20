from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def database_config_from_url(database_url):
    """Return a Django PostgreSQL config, or None when no URL is configured."""
    if not database_url:
        return None

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use the postgres:// or postgresql:// scheme.")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ImproperlyConfigured("DATABASE_URL must include a database host and database name.")

    try:
        port = parsed.port
    except ValueError as error:
        raise ImproperlyConfigured("DATABASE_URL contains an invalid database port.") from error

    options = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
        if key in {"sslmode", "connect_timeout", "application_name"} and values
    }
    options.setdefault("sslmode", "require")
    options.setdefault("options", "-c lock_timeout=5000")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": port or "",
        "OPTIONS": options,
        "CONN_HEALTH_CHECKS": True,
    }


def sqlite_database_config(name):
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": name,
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL",
        },
    }
