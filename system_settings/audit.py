SENSITIVE_KEYS = {"password", "temporary_password", "token", "api_key", "secret", "secrets", "authorization", "encrypted_secrets", "smtp_password", "integration_encryption_key", "otp", "otp_code", "id_number", "national_id", "aadhaar", "pan", "file", "file_contents", "content"}

from core.middleware.rate_limit import client_ip


def sanitize(value):
    if isinstance(value, dict):
        return {key: ("[redacted]" if key.lower() in SENSITIVE_KEYS else sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def request_ip(request):
    return client_ip(request)


def log_audit(*, request, organization=None, project=None, module, action, details=None, target=None, payload_before=None, payload_after=None):
    from .models import AuditLog
    if target is not None and action not in {"approve", "reject"} and module != "operations":
        existing = AuditLog.objects.filter(
            target_type=target.__class__.__name__,
            target_id=str(target.pk),
            user=request.user if request and request.user.is_authenticated else None,
            route=request.path if request else "",
        ).order_by("-pk").first()
        if existing is not None:
            return existing
    record = AuditLog.objects.create(organization=organization, project=project, user=request.user if request and request.user.is_authenticated else None,
                                   module=module, action=action, method=request.method if request else "",
                                   route=request.path if request else "", ip_address=request_ip(request) if request else None,
                                   details=sanitize(details or {}), payload_before=sanitize(payload_before) if payload_before is not None else None,
                                   payload_after=sanitize(payload_after) if payload_after is not None else None,
                                   target_type=target.__class__.__name__ if target else "", target_id=str(target.pk) if target else "")
    if request is not None:
        request._audit_logged = True
    return record


def log_command_audit(*, module, action, route, details=None, organization=None, project=None):
    from .models import AuditLog
    return AuditLog.objects.create(
        organization_id=getattr(organization, "pk", None),
        project_id=getattr(project, "pk", None),
        user=None,
        module=module,
        action=action,
        method="COMMAND",
        route=route,
        details=sanitize(details or {}),
    )


_UNSET = object()


def log_bulk_audit(*, request=None, module, action, instances=None, record_ids=None,
                   organization=_UNSET, project=_UNSET, before=None, after=None,
                   changed_values=None, target_type="", route=None, user=None):
    """Write one aggregate immutable row for a bulk mutation."""
    from .models import AuditLog

    items = list(instances or [])
    ids = list(record_ids or [item.pk for item in items])
    if not target_type and items:
        target_type = items[0].__class__.__name__
    if organization is _UNSET and items:
        organization = getattr(items[0], "organization", None)
    elif organization is _UNSET:
        organization = None
    if project is _UNSET and items:
        project = getattr(items[0], "project", None)
    elif project is _UNSET:
        project = None
    return AuditLog.objects.create(
        organization=organization,
        project=project,
        user=(request.user if request and request.user.is_authenticated else user),
        module=module,
        action=action,
        method=request.method if request else "COMMAND",
        route=route or (request.path if request else "command:unknown"),
        ip_address=request_ip(request) if request else None,
        details=sanitize({
            "record_ids": ids,
            "changed_values": changed_values or {},
            **({"before": before} if before is not None else {}),
            **({"after": after} if after is not None else {}),
        }),
        payload_before=sanitize(before) if before is not None else None,
        payload_after=sanitize(after) if after is not None else None,
        target_type=target_type,
        target_id=",".join(str(item) for item in ids),
    )
