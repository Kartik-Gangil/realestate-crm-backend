"""Shared assertion for NFR-P12-01 downloads."""


def assert_protected_download(test, response, content, content_type):
    test.assertEqual(response.status_code, 200)
    test.assertEqual(response.content, content)
    test.assertEqual(response["Content-Type"], content_type)
    test.assertTrue(response["Content-Disposition"].startswith("attachment;"))
    test.assertEqual(response["X-Content-Type-Options"], "nosniff")
    test.assertEqual(response["Content-Security-Policy"], "sandbox")
    test.assertEqual(response["Cache-Control"], "private, no-store")
