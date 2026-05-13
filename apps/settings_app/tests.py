from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.settings_app.models import SettingsAuditLog, SystemSettings
from apps.users.models import Role, User


class SystemSettingsApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="settings-admin@example.com",
            password="AdminPass123!",
            first_name="Settings",
            last_name="Admin",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="settings-invigilator@example.com",
            password="InvigilatorPass123!",
            first_name="Settings",
            last_name="Invigilator",
            role=Role.INVIGILATOR,
        )
        self.url = reverse("system-settings")

    def test_admin_can_retrieve_singleton_settings(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["orgName"], "Lead Edge Ltd")
        self.assertEqual(response.data["data"]["defaultPassBoundary"], 60)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_admin_can_patch_settings_and_audit_changes(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            self.url,
            {
                "orgName": "Lead Edge Test Centre",
                "defaultPassBoundary": 55,
                "defaultMeritBoundary": 70,
                "defaultDistinctionBoundary": 85,
                "defaultQuestionsPerExam": 50,
                "defaultStrictMode": False,
                "allowMockTests": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["orgName"], "Lead Edge Test Centre")
        settings_obj = SystemSettings.load()
        self.assertEqual(settings_obj.updated_by, self.admin)
        self.assertEqual(settings_obj.default_questions_per_exam, 50)
        self.assertFalse(settings_obj.default_strict_mode)
        self.assertFalse(settings_obj.allow_mock_tests)
        self.assertGreaterEqual(SettingsAuditLog.objects.count(), 4)

    def test_invalid_grade_boundaries_are_rejected(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            self.url,
            {
                "defaultPassBoundary": 80,
                "defaultMeritBoundary": 70,
                "defaultDistinctionBoundary": 85,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_cannot_access_settings(self):
        self.client.force_authenticate(user=self.invigilator)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
