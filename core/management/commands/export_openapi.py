import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver


PATH_PARAMETER_RE = re.compile(r"<(?:(?:[A-Za-z_][A-Za-z0-9_]*):)?([A-Za-z_][A-Za-z0-9_]*)>")


def _route(pattern):
    return getattr(pattern, "_route", str(pattern))


def _walk(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + _route(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + _route(pattern.pattern), pattern.callback


def _openapi_path(route):
    route = "/" + route.lstrip("/")
    return PATH_PARAMETER_RE.sub(r"{\1}", route)


def _operation(path, callback, method):
    spec = getattr(callback, "crm_endpoint_spec", {})
    scope = spec.get("scope")
    operation = {
        "operationId": f"{method.lower()}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '') or 'root'}",
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}},
            }
        },
    }
    if path == "/metrics":
        operation["responses"]["200"]["content"] = {"text/plain": {"schema": {"type": "string"}}}
    if scope:
        operation["x-crm-scope"] = scope
        operation["x-permissions"] = spec.get("permissions", {})
        if scope != "public":
            operation["security"] = [{"bearerAuth": []}]
        if scope == "project":
            operation.setdefault("parameters", []).append({
                "name": "X-Project-ID",
                "in": "header",
                "required": True,
                "schema": {"type": "integer"},
            })
    for name in re.findall(r"{([^}]+)}", path):
        operation.setdefault("parameters", []).append({
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        })
    return operation


class Command(BaseCommand):
    help = "Export the route-derived OpenAPI 3.1 document."

    def add_arguments(self, parser):
        parser.add_argument("--output", default=str(Path(settings.BASE_DIR) / "docs" / "openapi.json"))

    def handle(self, *args, **options):
        paths = {}
        for route, callback in _walk(get_resolver().url_patterns):
            path = _openapi_path(route)
            if not (path.startswith("/api/v1/") or path in {"/healthz", "/readyz", "/metrics"}):
                continue
            spec = getattr(callback, "crm_endpoint_spec", {})
            methods = spec.get("methods")
            if not methods:
                methods = getattr(callback, "allowed_methods", None)
            if not methods:
                methods = [
                    method.upper()
                    for method in getattr(getattr(callback, "cls", None), "http_method_names", ("get",))
                    if method not in {"options", "head"}
                ]
            for method in methods:
                method = str(method).lower()
                if method in {"options", "head"}:
                    continue
                paths.setdefault(path, {})[method] = _operation(path, callback, method)
        document = {
            "openapi": "3.1.0",
            "info": {"title": "Shriji CRM API", "version": "1.0.0"},
            "servers": [{"url": "/"}],
            "paths": dict(sorted(paths.items())),
            "components": {
                "securitySchemes": {
                    "bearerAuth": {"type": "http", "scheme": "bearer"},
                },
                "schemas": {
                    "Envelope": {
                        "type": "object",
                        "required": ["success", "data", "error", "meta"],
                        "properties": {
                            "success": {"type": "boolean"},
                            "data": {},
                            "error": {"oneOf": [{"type": "object"}, {"type": "null"}]},
                            "meta": {
                                "type": "object",
                                "required": ["timestamp", "project_id"],
                                "properties": {
                                    "timestamp": {"type": "string", "format": "date-time"},
                                    "project_id": {"oneOf": [{"type": "integer"}, {"type": "null"}]},
                                },
                            },
                        },
                    },
                    "Project": {"type": "object", "required": ["id", "name", "code"]},
                    "Notification": {"type": "object", "required": ["id", "type", "title", "body", "status"]},
                },
            },
        }
        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.stdout.write(f"Wrote {output}")
