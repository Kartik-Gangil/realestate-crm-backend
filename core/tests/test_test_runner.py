"""TASK-SEC-001 / G-4: the test suite never writes into the real Backend/media folder."""

import base64
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase
from django.test.runner import DiscoverRunner

from core.test_runner import CrmTestRunner

REAL_MEDIA = (Path(settings.BASE_DIR) / "media").resolve()


class CrmTestRunnerTests(SimpleTestCase):
    def test_the_project_uses_the_crm_runner(self):
        self.assertEqual(settings.TEST_RUNNER, "core.test_runner.CrmTestRunner")

    def test_uploads_during_tests_go_to_a_temporary_folder(self):
        media = Path(settings.MEDIA_ROOT).resolve()
        self.assertNotEqual(media, REAL_MEDIA)
        self.assertTrue(media.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        name = default_storage.save("runner-check/sample.txt", ContentFile(b"x"))
        self.addCleanup(default_storage.delete, name)
        self.assertTrue((media / name).is_file())
        self.assertFalse((REAL_MEDIA / name).exists())

    def test_tests_use_their_own_key_and_an_empty_legacy_folder(self):
        self.assertEqual(len(base64.urlsafe_b64decode(settings.FILE_ENCRYPTION_KEY)), 32)
        legacy = Path(settings.LEGACY_MEDIA_ROOT).resolve()
        self.assertNotEqual(legacy, REAL_MEDIA)
        self.assertTrue(legacy.is_relative_to(Path(tempfile.gettempdir()).resolve()))

    def test_the_runner_creates_and_removes_its_folder(self):
        outer = settings.MEDIA_ROOT
        outer_legacy = settings.LEGACY_MEDIA_ROOT
        outer_key = settings.FILE_ENCRYPTION_KEY
        runner = CrmTestRunner(verbosity=0)
        with mock.patch.object(DiscoverRunner, "setup_test_environment"), \
                mock.patch.object(DiscoverRunner, "teardown_test_environment"):
            runner.setup_test_environment()
            inner = Path(settings.MEDIA_ROOT)
            inner_legacy = Path(settings.LEGACY_MEDIA_ROOT)
            self.assertTrue(inner.is_dir())
            self.assertTrue(inner_legacy.is_dir())
            self.assertNotEqual(str(inner), str(outer))
            self.assertNotEqual(settings.FILE_ENCRYPTION_KEY, outer_key)
            runner.teardown_test_environment()
        self.assertFalse(inner.exists())
        self.assertFalse(inner_legacy.exists())
        self.assertEqual(settings.MEDIA_ROOT, outer)
        self.assertEqual(settings.LEGACY_MEDIA_ROOT, outer_legacy)
        self.assertEqual(settings.FILE_ENCRYPTION_KEY, outer_key)
