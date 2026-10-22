"""TASK-SEC-001 acceptance: /media/... returns 404, even with DEBUG on."""
import importlib

from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve

import config.urls


class MediaRouteTests(SimpleTestCase):
    def tearDown(self):
        importlib.reload(config.urls)
        clear_url_caches()

    def test_media_is_not_routed_even_with_debug_on(self):
        with override_settings(DEBUG=True):
            importlib.reload(config.urls)
            clear_url_caches()
            with self.assertRaises(Resolver404):
                resolve("/media/documents/any-file.pdf")

    def test_a_media_request_is_404(self):
        self.assertEqual(self.client.get("/media/documents/any-file.pdf").status_code, 404)
