from django.test import SimpleTestCase

from leads.phone import normalize_phone


class LeadPhoneNormalizationTests(SimpleTestCase):
    """FR-P4-04 (v2.5) / NFR-P4-02 phone-cleaning contract."""

    def test_12_digit_91_prefix_becomes_indian_phone(self):
        self.assertEqual(normalize_phone("919876543210"), "+919876543210")

    def test_91_prefix_with_9_or_11_following_digits_is_rejected(self):
        self.assertIsNone(normalize_phone("91987654321"))
        self.assertIsNone(normalize_phone("9198765432100"))

    def test_existing_indian_normalization_cases_still_pass(self):
        self.assertEqual(normalize_phone("9876543210"), "+919876543210")
        self.assertEqual(normalize_phone("09876543210"), "+919876543210")
        self.assertEqual(normalize_phone("+91 98765 43210"), "+919876543210")

    def test_other_country_code_is_preserved(self):
        self.assertEqual(normalize_phone("+44 20 7946 0958"), "+442079460958")

    def test_unusable_phone_is_rejected(self):
        self.assertIsNone(normalize_phone("not-a-phone"))
