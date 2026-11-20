import json
from contextvars import ContextVar

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from core.audit_context import audit_signals_suppressed, get_current_request
from core.audit_registry import AUDIT_MODEL_LABELS
from core.middleware.rate_limit import client_ip
from system_settings.audit import sanitize


_snapshots = ContextVar("crm_audit_snapshots", default=None)
_deletion_root = ContextVar("crm_audit_deletion_root", default=None)
_deletion_tokens = ContextVar("crm_audit_deletion_tokens", default=None)
_deletion_active = ContextVar("crm_audit_deletion_active", default=None)


def begin_deletion_audit(root_type, object_id):
    """Mark the root of a deletion before Django cascades its children."""
    return _deletion_root.set((root_type, object_id))


def end_deletion_audit(token):
    _deletion_root.reset(token)


def _snapshot_store():
    store = _snapshots.get()
    if store is None:
        store = {}
        _snapshots.set(store)
    return store


def _deletion_token_store():
    store = _deletion_tokens.get()
    if store is None:
        store = {}
        _deletion_tokens.set(store)
    return store


def _deletion_active_store():
    store = _deletion_active.get()
    if store is None:
        store = set()
        _deletion_active.set(store)
    return store


def _json_value(value):
    if hasattr(value, "field") and hasattr(value, "name"):
        return "[redacted]"
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _field_values(instance):
    return {
        field.name: _json_value(field.value_from_object(instance))
        for field in instance._meta.concrete_fields
    }


def _module_for(instance):
    if instance._meta.app_label == "auth":
        return "users"
    if instance._meta.app_label == "system_settings":
        return "settings"
    return instance._meta.app_label


def _organization_project(instance):
    organization_id = getattr(instance, "organization_id", None)
    project_id = getattr(instance, "project_id", None)
    if project_id and not organization_id:
        project = getattr(instance, "project", None)
        organization_id = getattr(project, "organization_id", None)
    if not organization_id:
        membership = getattr(instance, "membership", None)
        organization_id = getattr(membership, "organization_id", None)
    if not project_id:
        project = getattr(instance, "project", None)
        project_id = getattr(project, "pk", None)
    if not project_id:
        for relation_name in ("booking", "customer", "plot", "agreement", "expense"):
            related = getattr(instance, relation_name, None)
            related_project = getattr(related, "project", None) if related is not None else None
            if related_project is None and related is not None:
                related_plot = getattr(related, "plot", None)
                related_project = getattr(related_plot, "project", None) if related_plot is not None else None
            if related_project is not None:
                project_id = related_project.pk
                organization_id = organization_id or related_project.organization_id
                break
    if not organization_id and getattr(instance, "pk", None) and instance._meta.label == "auth.User":
        organization_id = (
            instance.organization_memberships.filter(is_active=True)
            .values_list("organization_id", flat=True)
            .first()
        )
    return organization_id, project_id


def _audit_values(instance, values):
    return sanitize(values or {})


def _write(instance, action, before, after):
    from system_settings.models import AuditLog

    request = get_current_request()
    organization_id, project_id = _organization_project(instance)
    details = {}
    if action == "delete":
        root = _deletion_root.get()
        if root and root[0] == "organization" and organization_id == root[1]:
            details["deleted_organization_id"] = organization_id
            organization_id = None
        if root and root[0] == "project" and project_id == root[1]:
            details["deleted_project_id"] = project_id
            project_id = None
        if instance._meta.label == "inventory.Project":
            details["deleted_project_id"] = instance.pk
            project_id = None
        elif instance._meta.label == "organizations.Organization":
            details["deleted_organization_id"] = instance.pk
            organization_id = None
        if organization_id and not apps.get_model("organizations", "Organization").objects.filter(pk=organization_id).exists():
            details["deleted_organization_id"] = organization_id
            organization_id = None
        if project_id and not apps.get_model("inventory", "Project").objects.filter(pk=project_id).exists():
            details["deleted_project_id"] = project_id
            project_id = None
    user = getattr(request, "user", None) if request is not None else None
    authenticated = bool(user is not None and getattr(user, "is_authenticated", False))
    route = getattr(request, "path", "") if request is not None else "command:unknown"
    method = getattr(request, "method", "") if request is not None else "COMMAND"
    action_override = getattr(request, "_audit_action", None) if request is not None else None
    AuditLog.objects.create(
        organization_id=organization_id,
        project_id=project_id,
        user=user if authenticated else None,
        module=_module_for(instance),
        action=action_override or action,
        method=method,
        route=route,
        ip_address=client_ip(request) if request is not None else None,
        details=details,
        payload_before=_audit_values(instance, before),
        payload_after=_audit_values(instance, after),
        target_type=instance.__class__.__name__,
        target_id=str(getattr(instance, "pk", "")),
    )


def _label(sender):
    return f"{sender._meta.app_label}.{sender.__name__}"


def _pre_save(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    _snapshot_store()[id(instance)] = _field_values(old)


def _post_save(sender, instance, created, **kwargs):
    if audit_signals_suppressed():
        _snapshot_store().pop(id(instance), None)
        return
    old = _snapshot_store().pop(id(instance), None)
    current = _field_values(instance)
    if created:
        before, after = {}, current
        action = "create"
    else:
        changed = [key for key in current if old and old.get(key) != current.get(key)]
        if not changed:
            return
        before = {key: old[key] for key in changed}
        after = {key: current[key] for key in changed}
        action = "update"
    _write(instance, action, before, after)


def _pre_delete(sender, instance, **kwargs):
    label = _label(sender)
    if label in {"organizations.Organization", "inventory.Project"} and _deletion_root.get() is None:
        root_type = "organization" if label == "organizations.Organization" else "project"
        token = _deletion_root.set((root_type, instance.pk))
        _deletion_token_store()[id(instance)] = token
    _deletion_active_store().add((label, id(instance)))
    _snapshot_store()[id(instance)] = _field_values(instance)


def _post_delete(sender, instance, **kwargs):
    if audit_signals_suppressed():
        _snapshot_store().pop(id(instance), None)
        _deletion_active_store().discard((_label(sender), id(instance)))
        return
    _write(instance, "delete", _snapshot_store().pop(id(instance), _field_values(instance)), {})
    _deletion_active_store().discard((_label(sender), id(instance)))
    if not _deletion_active_store():
        for token in _deletion_token_store().values():
            _deletion_root.reset(token)
        _deletion_token_store().clear()


def register_audit_signals():
    for label in AUDIT_MODEL_LABELS:
        app_label, model_name = label.split(".", 1)
        model = apps.get_model(app_label, model_name)
        pre_save.connect(_pre_save, sender=model, dispatch_uid=f"phase3-audit-pre-save:{label}")
        post_save.connect(_post_save, sender=model, dispatch_uid=f"phase3-audit-post-save:{label}")
        pre_delete.connect(_pre_delete, sender=model, dispatch_uid=f"phase3-audit-pre-delete:{label}")
        post_delete.connect(_post_delete, sender=model, dispatch_uid=f"phase3-audit-post-delete:{label}")
