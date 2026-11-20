import hmac

from django.conf import settings
from django.http import HttpResponse

from core.endpoint import public_endpoint
from core.metrics import prometheus_text


@public_endpoint
def metrics(request):
    configured = str(getattr(settings, "METRICS_TOKEN", ""))
    if not configured:
        return HttpResponse(status=404)
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(
        token.encode("utf-8"), configured.encode("utf-8")
    ):
        return HttpResponse(status=401)
    return HttpResponse(prometheus_text(), content_type="text/plain; version=0.0.4")
