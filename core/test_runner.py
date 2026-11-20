"""Runs the suite with uploads in a throwaway folder (TASK-SEC-001, G-4)."""

import shutil
import tempfile
import base64
import os
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class CrmTestRunner(DiscoverRunner):
    @staticmethod
    def _temporary_root(prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
        backend = Path(settings.BASE_DIR).resolve()
        if root == backend or root.is_relative_to(backend):
            shutil.rmtree(root, ignore_errors=True)
            raise RuntimeError("Test upload roots must never be inside Backend.")
        return str(root)

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_root = self._temporary_root("crm-test-media-")
        self._legacy_root = self._temporary_root("crm-test-legacy-media-")
        self._media_override = override_settings(
            MEDIA_ROOT=self._media_root,
            LEGACY_MEDIA_ROOT=self._legacy_root,
            FILE_ENCRYPTION_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
        )
        self._media_override.enable()
        self._password_hashers_override = override_settings(
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        )
        self._password_hashers_override.enable()
        self._rate_limit_override = override_settings(
            RATE_LIMIT_PUBLIC_PER_MINUTE=10000,
            RATE_LIMIT_API_PER_MINUTE=10000,
        )
        self._rate_limit_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._rate_limit_override.disable()
        self._password_hashers_override.disable()
        self._media_override.disable()
        shutil.rmtree(self._media_root, ignore_errors=True)
        shutil.rmtree(self._legacy_root, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
