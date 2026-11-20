from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase
from django.urls import resolve, reverse


LEGACY_V1_ROUTE_PAIRS = (
    (
        "/api/organizations/acme/employees/",
        "/api/v1/organizations/acme/employees/",
    ),
    (
        "/api/organizations/acme/settings/general/",
        "/api/v1/organizations/acme/settings/general/",
    ),
    (
        "/api/organizations/acme/sitevisits/",
        "/api/v1/organizations/acme/sitevisits/",
    ),
    (
        "/api/organizations/acme/inventory/plots/",
        "/api/v1/organizations/acme/inventory/plots/",
    ),
    (
        "/api/organizations/acme/documents/",
        "/api/v1/organizations/acme/documents/",
    ),
    (
        "/api/organizations/acme/registries/",
        "/api/v1/organizations/acme/registries/",
    ),
    ("/api/expenses/", "/api/v1/expenses/"),
    ("/api/categories/", "/api/v1/categories/"),
)


class ApiV1RouteTests(SimpleTestCase):
    """G-2 / FR-P0-02: v1 mounts mirror legacy views without changing aliases."""

    def test_each_v1_representative_route_resolves_to_the_legacy_view_g_2(self):
        for legacy_path, v1_path in LEGACY_V1_ROUTE_PAIRS:
            with self.subTest(v1_path=v1_path):
                self.assertIs(resolve(v1_path).func, resolve(legacy_path).func)

    def test_legacy_routes_and_reverse_names_remain_unchanged_g_2(self):
        for legacy_path, _ in LEGACY_V1_ROUTE_PAIRS:
            with self.subTest(legacy_path=legacy_path):
                self.assertIsNotNone(resolve(legacy_path).func)

        legacy_reverses = {
            "employee-list": {
                "kwargs": {"organization_slug": "acme"},
                "path": "/api/organizations/acme/employees/",
            },
            "leads:site-visit": {
                "kwargs": {"organization_slug": "acme"},
                "path": "/api/organizations/acme/sitevisits/",
            },
            "inventory:plots": {
                "kwargs": {"organization_slug": "acme"},
                "path": "/api/organizations/acme/inventory/plots/",
            },
            "documents:list": {
                "kwargs": {"organization_slug": "acme"},
                "path": "/api/organizations/acme/documents/",
            },
            "expense-list": {
                "kwargs": {},
                "path": "/api/expenses/",
            },
        }
        for name, expected in legacy_reverses.items():
            with self.subTest(name=name):
                self.assertEqual(reverse(name, kwargs=expected["kwargs"]), expected["path"])

        v1_reverses = {
            "organizations-v1:employee-list": "/api/v1/organizations/acme/employees/",
            "leads-v1:list": "/api/v1/organizations/acme/leads/",
            "inventory-v1:plots": "/api/v1/organizations/acme/inventory/plots/",
            "documents-v1:list": "/api/v1/organizations/acme/documents/",
            "expenses-v1:expense-list": "/api/v1/expenses/",
        }
        for name, expected_path in v1_reverses.items():
            with self.subTest(name=name):
                kwargs = {} if name.startswith("expenses-v1:") else {"organization_slug": "acme"}
                self.assertEqual(reverse(name, kwargs=kwargs), expected_path)

    def test_django_check_has_no_url_namespace_warnings_g_2(self):
        output = StringIO()
        call_command("check", stdout=output)
        self.assertNotIn("URL namespace", output.getvalue())
