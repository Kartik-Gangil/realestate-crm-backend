SENSITIVE_KEYS = {"password", "temporary_password", "token", "api_key", "secret", "secrets", "authorization", "encrypted_secrets", "smtp_password", "integration_encryption_key"}


def sanitize(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def request_ip(request):
    # Proxy headers are intentionally ignored until a trusted-proxy deployment is configured.
    return request.META.get("REMOTE_ADDR")


def log_audit(*, request, organization=None, module, action, details=None, target=None):
    from .models import AuditLog
    return AuditLog.objects.create(organization=organization, actor=request.user if request and request.user.is_authenticated else None,
                                   module=module, action=action, ip_address=request_ip(request), details=sanitize(details or {}),
                                   target_type=target.__class__.__name__ if target else "", target_id=str(target.pk) if target else "")
