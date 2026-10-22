"""Small, dependency-free environment configuration helpers for Django settings."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def env_str(name, default=""):
    value = os.environ.get(name, "").strip()
    return value if value else default


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def env_list(name, default=()):
    value = os.environ.get(name, "").strip()
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be set.")
    return value


def read_env_file(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_env_file(default_path):
    default_path = Path(default_path)
    selected = os.environ.get("DJANGO_ENV_FILE", "").strip()
    if not selected:
        if not default_path.is_file():
            return None
        read_env_file(default_path)
        return default_path
    if selected.lower() == "none":
        return None
    path = Path(selected)
    if not path.is_absolute():
        path = default_path.parent / path
    if not path.is_file():
        raise ImproperlyConfigured(f"DJANGO_ENV_FILE must name an existing file: {selected}")
    read_env_file(path)
    return path
