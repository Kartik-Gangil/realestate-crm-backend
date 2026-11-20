import hashlib
import hmac
import json
import time

from django.core.cache import caches
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from inventory.models import Project
from system_settings.integrations import decrypt_secret
from system_settings.models import IntegrationConfiguration

from .duplicate import score_duplicates
from .models import Lead
from .views import _apply_payload


def _integration(organization, integration_type):
    item = IntegrationConfiguration.objects.filter(
        organization=organization,
        integration_type=integration_type,
        enabled=True,
    ).first()
    if not item or not item.encrypted_secrets:
        return None
    return item


def _mapped_project(organization, configuration, form_id):
    mapping = (configuration.configuration or {}).get("form_project_mapping", {})
    value = mapping.get(str(form_id))
    if value is None:
        return None
    project_query = Project.objects.filter(organization=organization)
    if (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, str) and value.isdigit()):
        return project_query.filter(pk=int(value)).first()
    return project_query.filter(code=value).first()


def _meta_fields(payload):
    values = {}
    for field in payload.get("field_data", []):
        name = str(field.get("name") or "").lower()
        value = (field.get("values") or [""])[0]
        values[name] = value
    return {
        "full_name": values.get("full_name") or values.get("name") or "Imported Lead",
        "phone": values.get("phone_number") or values.get("phone") or "",
        "email": values.get("email") or "",
        "source": "ig" if str(payload.get("platform") or "").lower() in {"ig", "instagram"} else "fb",
        "external_source": "meta",
        "external_id": str(payload.get("leadgen_id") or payload.get("lead_id") or ""),
    }


def _google_fields(payload):
    values = {}
    for field in payload.get("user_column_data", []):
        key = str(field.get("column_id") or field.get("column_name") or "").upper()
        values[key] = field.get("string_value") or (field.get("values") or [""])[0]
    return {
        "full_name": values.get("FULL_NAME") or values.get("NAME") or "Imported Lead",
        "phone": values.get("PHONE_NUMBER") or values.get("PHONE") or "",
        "email": values.get("EMAIL") or "",
        "source": "google",
        "external_source": "google",
        "external_id": str(payload.get("lead_id") or payload.get("leadId") or payload.get("gcl_id") or ""),
    }


def _signature_ok(request, secret):
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", ""))


def _webhook_allowed(request, connector):
    now_bucket = int(time.time() // 60)
    key = f"crm-lead-webhook:{connector}:{request.META.get('REMOTE_ADDR', 'unknown')}:{now_bucket}"
    cache = caches["ratelimit"]
    count = cache.get(key, 0)
    if count >= 60:
        return False
    cache.set(key, count + 1, 61)
    return True


def _save_or_preview(organization, fields, project, *, preview=False):
    matches = score_duplicates(organization, project, fields)
    result = {"project_id": project.id, "lead_code": None, "external_id": fields["external_id"], "matches": matches}
    if preview:
        result["lead"] = fields
        return result, False
    existing = Lead.objects.filter(
        organization=organization,
        project=project,
        external_source=fields["external_source"],
        external_id=fields["external_id"],
    ).first()
    if existing:
        result["lead_code"] = existing.lead_code
        result["idempotent"] = True
        return result, False
    payload = dict(fields)
    name_parts = str(payload.pop("full_name", "Imported Lead")).split(None, 1)
    payload["first_name"] = name_parts[0]
    payload["last_name"] = name_parts[1] if len(name_parts) == 2 else ""
    with transaction.atomic():
        lead = _apply_payload(Lead(project=project), payload, organization, project=project)
        lead.save()
    result["lead_code"] = lead.lead_code
    result["lead"] = {"id": lead.id, "lead_code": lead.lead_code, "source": lead.source}
    return result, True


def receive_meta(request, organization):
    if not _webhook_allowed(request, "meta"):
        return Response({"detail": "Webhook rate limit exceeded."}, status=429)
    config = _integration(organization, IntegrationConfiguration.Type.META_ADS)
    if not config:
        return Response({"code": "not_connected"}, status=409)
    secret = decrypt_secret(config.encrypted_secrets).get("app_secret", "")
    if not secret or not _signature_ok(request, secret):
        return Response({"detail": "Invalid signature."}, status=403)
    payload = json.loads(request.body.decode("utf-8"))
    project = _mapped_project(organization, config, payload.get("form_id"))
    if project is None:
        return Response({"form_id": ["The form is not mapped to this organization."]}, status=400)
    result, created = _save_or_preview(organization, _meta_fields(payload), project)
    if created:
        config.last_synced_at = timezone.now()
        config.save(update_fields=("last_synced_at", "updated_at"))
    return Response(result, status=201 if created else 200)


def receive_google(request, organization):
    if not _webhook_allowed(request, "google"):
        return Response({"detail": "Webhook rate limit exceeded."}, status=429)
    config = _integration(organization, IntegrationConfiguration.Type.GOOGLE_ADS)
    if not config:
        return Response({"code": "not_connected"}, status=409)
    secrets = decrypt_secret(config.encrypted_secrets)
    payload = json.loads(request.body.decode("utf-8"))
    if not secrets.get("google_key") or payload.get("google_key") != secrets.get("google_key"):
        return Response({"detail": "Invalid Google key."}, status=403)
    project = _mapped_project(organization, config, payload.get("form_id"))
    if project is None:
        return Response({"form_id": ["The form is not mapped to this organization."]}, status=400)
    result, created = _save_or_preview(organization, _google_fields(payload), project)
    if created:
        config.last_synced_at = timezone.now()
        config.save(update_fields=("last_synced_at", "updated_at"))
    return Response(result, status=201 if created else 200)


def sync(request, organization, integration_type, project):
    config = _integration(organization, integration_type)
    if not config:
        return Response({"code": "not_connected"}, status=409)
    if "payloads" in request.data:
        return Response({"payloads": ["Sync reads only the integration's stored sample data."]}, status=400)
    payloads = (config.configuration or {}).get("mock_payloads", [])
    selected_external_ids = request.data.get("selected_external_ids")
    if selected_external_ids is not None:
        if not isinstance(selected_external_ids, list) or not all(
            isinstance(external_id, (str, int)) for external_id in selected_external_ids
        ):
            return Response({"selected_external_ids": ["Provide a list of external lead IDs."]}, status=400)
        selected_external_ids = {str(external_id) for external_id in selected_external_ids}
    preview = bool(request.data.get("preview"))
    results = []
    created = 0
    for payload in payloads:
        fields = _meta_fields(payload) if integration_type == IntegrationConfiguration.Type.META_ADS else _google_fields(payload)
        if selected_external_ids is not None and fields["external_id"] not in selected_external_ids:
            continue
        mapped_project = _mapped_project(organization, config, payload.get("form_id"))
        if mapped_project is None or mapped_project.id != project.id:
            continue
        result, was_created = _save_or_preview(organization, fields, mapped_project, preview=preview)
        results.append(result)
        created += was_created
    if not preview and created:
        config.last_synced_at = timezone.now()
        config.save(update_fields=("last_synced_at", "updated_at"))
    return Response({"preview": preview, "leads": results, "created": created}, status=200)
