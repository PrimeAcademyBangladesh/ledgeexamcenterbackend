from rest_framework import status
from rest_framework.test import APITestCase

from apps.exams.models import ExamConfig, ExamSession
from apps.invigilators.models import InvigilatorAvailability
from apps.qualifications.models import Level, Qualification, Sector
from apps.users.models import Role, User


class InvigilatorAvailabilityApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="availability-admin@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="availability-invigilator@example.com",
            password="InvigilatorPass123!",
            first_name="Ivy",
            last_name="Gilator",
            role=Role.INVIGILATOR,
        )
        self.other_invigilator = User.objects.create_user(
            email="availability-other@example.com",
            password="InvigilatorPass123!",
            first_name="Nora",
            last_name="Proctor",
            role=Role.INVIGILATOR,
        )

        self.slot = InvigilatorAvailability.objects.create(
            user=self.invigilator,
            day_of_week=0,
            start_time="09:00",
            end_time="11:00",
        )

    def test_my_sessions_includes_learner_uln(self):
        learner = User.objects.create_user(
            email="availability-learner@example.com",
            password="LearnerPass123!",
            first_name="Lina",
            last_name="Student",
            role=Role.LEARNER,
        )
        learner.learner_profile.uln = "1234567890"
        learner.learner_profile.save(update_fields=["uln"])

        level = Level.objects.create(name="level-4")
        sector = Sector.objects.create(name="Business", code="BUS")
        qualification = Qualification.objects.create(
            code="QUAL-SESSION",
            title="Session Qualification",
            sector=sector,
            level=level,
            is_active=True,
        )
        exam_config = ExamConfig.objects.create(
            title="Knowledge Exam",
            qualification=qualification,
            questions_per_exam=5,
            time_limit_minutes=60,
            status="published",
        )
        ExamSession.objects.create(
            exam_config=exam_config,
            learner=learner,
            invigilator=self.invigilator,
            scheduled_date="2026-06-01",
            scheduled_time="09:00",
            pin="123456",
            pin_active=True,
            status="scheduled",
        )

        self.client.force_authenticate(user=self.invigilator)
        response = self.client.get("/invigilators/me/sessions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["learner_uln"], "1234567890")

    def test_admin_can_list_invigilator_availability(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(f"/invigilators/{self.invigilator.id}/availability/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.slot.id))

    def test_admin_create_rejects_overlapping_slot_with_human_readable_error(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            f"/invigilators/{self.invigilator.id}/availability/",
            {
                "dayOfWeek": 0,
                "startTime": "10:00:00",
                "endTime": "12:00:00",
                "isActive": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("Overlapping time ranges are not allowed", response.data["message"])
        self.assertIn("non_field_errors", response.data["errors"])

    def test_admin_can_update_slot_when_no_overlap_exists(self):
        other_slot = InvigilatorAvailability.objects.create(
            user=self.invigilator,
            day_of_week=0,
            start_time="12:00",
            end_time="13:00",
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"/invigilators/{self.invigilator.id}/availability/{other_slot.id}/",
            {"startTime": "13:00:00", "endTime": "14:00:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        other_slot.refresh_from_db()
        self.assertEqual(other_slot.start_time.isoformat(), "13:00:00")
        self.assertEqual(other_slot.end_time.isoformat(), "14:00:00")

    def test_admin_patch_rejects_overlap_with_existing_slot(self):
        other_slot = InvigilatorAvailability.objects.create(
            user=self.invigilator,
            day_of_week=0,
            start_time="12:00",
            end_time="13:00",
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"/invigilators/{self.invigilator.id}/availability/{other_slot.id}/",
            {"startTime": "10:30:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Monday", response.data["message"])
        self.assertIn("09:00-11:00", response.data["message"])

    def test_invigilator_can_update_own_slot_from_me_endpoint(self):
        self.client.force_authenticate(user=self.invigilator)

        response = self.client.patch(
            f"/invigilators/me/availability/{self.slot.id}/",
            {"startTime": "08:00:00", "endTime": "10:00:00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time.isoformat(), "08:00:00")

    def test_invigilator_cannot_manage_another_invigilators_availability(self):
        self.client.force_authenticate(user=self.other_invigilator)

        response = self.client.get(f"/invigilators/{self.invigilator.id}/availability/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(response.data["success"])
        self.assertIn("permission", response.data["errors"]["detail"][0].lower())

    def test_admin_can_delete_slot(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.delete(
            f"/invigilators/{self.invigilator.id}/availability/{self.slot.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            InvigilatorAvailability.objects.filter(pk=self.slot.id).exists()
        )
