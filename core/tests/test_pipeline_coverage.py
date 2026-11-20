from pathlib import Path

from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver


def _view_callbacks(patterns, *, under_admin=False):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _view_callbacks(
                pattern.url_patterns,
                under_admin=under_admin or str(pattern.pattern).startswith("admin/"),
            )
        elif isinstance(pattern, URLPattern) and not under_admin:
            yield pattern, pattern.callback


def _callback_name(callback):
    source = getattr(callback, "cls", None)
    if source is not None:
        return f"{source.__module__}.{source.__name__}"
    return f"{callback.__module__}.{callback.__name__}"


class PipelineCoverageTests(SimpleTestCase):
    """GNFR-14: every route is marked or explicitly owned for conversion."""

    def _pending(self):
        pending_path = Path(__file__).resolve().parents[3] / "scripts" / "pipeline-pending.txt"
        if not pending_path.is_file():
            return {}
        pending = {}
        for line in pending_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            view_name, task, phase = [part.strip() for part in line.split("|", 2)]
            pending[view_name] = (task, phase)
        return pending

    def test_every_route_is_marked_or_owned_by_pipeline_pending_gnfr_14(self):
        pending = self._pending()
        missing = []
        for pattern, callback in _view_callbacks(get_resolver().url_patterns):
            if not (hasattr(callback, "crm_endpoint_spec") or getattr(callback, "public_endpoint", False)):
                if _callback_name(callback) not in pending:
                    missing.append(_callback_name(callback))

        self.assertEqual(missing, [], "add crm_endpoint, or add it to pipeline-pending.txt with its owning task")

    def test_pipeline_pending_has_valid_owners_and_no_marked_views_gnfr_14(self):
        pending = self._pending()
        invalid = [name for name, (task, phase) in pending.items() if not task or not phase]
        marked = []
        callbacks = {_callback_name(callback): callback for _, callback in _view_callbacks(get_resolver().url_patterns)}
        for name in pending:
            callback = callbacks.get(name)
            if callback and (hasattr(callback, "crm_endpoint_spec") or getattr(callback, "public_endpoint", False)):
                marked.append(name)

        self.assertEqual(invalid, [])
        self.assertEqual(marked, [], "remove views that are now marked from pipeline-pending.txt")
