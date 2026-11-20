from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase


class DatabaseCacheTests(TestCase):
    """G-3 item 4 / FR-P2-02 database cache foundation."""

    def test_default_cache_is_database_cache_on_crm_cache_g_3_item_4(self):
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.db.DatabaseCache",
        )
        self.assertEqual(settings.CACHES["default"]["LOCATION"], "crm_cache")

    def test_database_cache_set_and_get_works_fr_p2_02(self):
        cache.set("task5-cache-key", {"status": "ok"}, timeout=60)
        self.assertEqual(cache.get("task5-cache-key"), {"status": "ok"})

    def test_cache_table_exists_after_migrate_g_3_item_4(self):
        self.assertIn("crm_cache", connection.introspection.table_names())

