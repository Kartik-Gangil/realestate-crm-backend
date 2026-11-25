"""Authentication status and error contract coverage [UAT-D51]."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class UatD51AuthTests(TestCase):
    def test_wrong_password_returns_401_invalid_credentials(self):
        get_user_model().objects.create_user(
            username="uat-d51@example.test",
            email="uat-d51@example.test",
            password="Correct123!",
        )

        response = APIClient().post(
            "/api/v1/auth/login/",
            {"email": "uat-d51@example.test", "password": "Wrong123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        payload = response.data.get("error", response.data)
        self.assertEqual(payload.get("code"), "invalid_credentials")
