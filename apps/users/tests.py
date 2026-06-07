# tests/test_auth.py

from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from apps.users.models import User, Role


class AuthTests(APITestCase):

    def setUp(self):
        self.password = "TestPass123!"
        self.user = User.objects.create_user(
            email="test@example.com",
            password=self.password,
            first_name="Test",
            last_name="User",
            role=Role.LEARNER,
        )

    def login(self):
        url = reverse("token_obtain_pair")
        response = self.client.post(url, {
            "email": self.user.email,
            "password": self.password
        })
        return response

    def authenticate(self):
        res = self.login()
        token = res.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    # ----------------------
    # LOGIN TESTS
    # ----------------------

    def test_login_success(self):
        res = self.login()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)
        self.assertIn("user", res.data)

    def test_login_invalid(self):
        url = reverse("token_obtain_pair")
        res = self.client.post(url, {
            "email": self.user.email,
            "password": "wrongpassword"
        })
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    # ----------------------
    # ME TEST
    # ----------------------

    def test_me_authenticated(self):
        self.authenticate()
        url = reverse("user_me")
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])
        self.assertEqual(res.data["data"]["user"]["email"], self.user.email)

    def test_me_unauthenticated(self):
        url = reverse("user_me")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    # ----------------------
    # CHANGE PASSWORD
    # ----------------------

    def test_change_password_success(self):
        self.authenticate()
        url = reverse("change_password")

        res = self.client.post(url, {
            "old_password": self.password,
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })

        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # login with new password
        login_res = self.client.post(reverse("token_obtain_pair"), {
            "email": self.user.email,
            "password": "NewPass123!"
        })
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_old(self):
        self.authenticate()
        url = reverse("change_password")

        res = self.client.post(url, {
            "old_password": "wrong",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ----------------------
    # FORGOT PASSWORD
    # ----------------------

    def test_forgot_password(self):
        url = reverse("forgot_password")

        res = self.client.post(url, {
            "email": self.user.email
        })

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

    def test_forgot_password_nonexistent(self):
        url = reverse("forgot_password")

        res = self.client.post(url, {
            "email": "fake@example.com"
        })

        self.assertEqual(res.status_code, status.HTTP_200_OK)

    # ----------------------
    # RESET PASSWORD
    # ----------------------

    def test_reset_password_invalid_token(self):
        url = reverse("reset_password")

        res = self.client.post(url, {
            "uid": "invalid",
            "token": "invalid",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # ----------------------
    # LOGOUT
    # ----------------------

    def test_logout_success(self):
        login_res = self.login()
        access = login_res.data["access"]
        refresh = login_res.data["refresh"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        url = reverse("logout")
        res = self.client.post(url, {
            "refresh": refresh
        })

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

    def test_logout_without_token(self):
        self.authenticate()
        url = reverse("logout")

        res = self.client.post(url, {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)