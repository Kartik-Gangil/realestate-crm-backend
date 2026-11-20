from contextvars import ContextVar


_request = ContextVar("crm_audit_request", default=None)
_suppress_signals = ContextVar("crm_audit_suppress_signals", default=False)


def get_current_request():
    return _request.get()


def set_current_request(request):
    return _request.set(request)


def reset_current_request(token):
    _request.reset(token)


def suppress_audit_signals():
    return _suppress_signals.set(True)


def reset_audit_signal_suppression(token):
    _suppress_signals.reset(token)


def set_audit_action(request, action):
    """Expose semantic actions to signals for Django and DRF request objects."""
    request._audit_action = action
    underlying = getattr(request, "_request", None)
    if underlying is not None:
        underlying._audit_action = action


def audit_signals_suppressed():
    return _suppress_signals.get()
