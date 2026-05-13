from datetime import date, time

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.exams.models import ExamConfig, ExamSession
from apps.learners.models import Enrollment, EnrollmentStatus
from apps.qualifications.models import Level, Qualification, Sector
from apps.users.models import Role, User


class LearnerUpdateTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="invigilator@example.com",
            password="InvigilatorPass123!",
            first_name="Ivy",
            last_name="Gilator",
            role=Role.INVIGILATOR,
        )
        self.other_invigilator = User.objects.create_user(
            email="other-invigilator@example.com",
            password="InvigilatorPass123!",
            first_name="Nora",
            last_name="Proctor",
            role=Role.INVIGILATOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="LearnerPass123!",
            first_name="Old",
            last_name="Name",
            role=Role.LEARNER,
        )
        self.profile = self.learner.learner_profile
        self.profile.phone = "0123456789"
        self.profile.uln = "1234567890"
        self.profile.save()

        self.level = Level.objects.create(name="level-3")
        self.sector = Sector.objects.create(name="Health", code="HEALTH")
        self.qualification = Qualification.objects.create(
            code="QUAL-1",
            title="Qualification One",
            sector=self.sector,
            level=self.level,
            is_active=True,
        )
        self.other_qualification = Qualification.objects.create(
            code="QUAL-2",
            title="Qualification Two",
            sector=self.sector,
            level=self.level,
            is_active=True,
        )
        self.exam_config = ExamConfig.objects.create(
            title="Knowledge Test One",
            qualification=self.qualification,
            questions_per_exam=1,
            time_limit_minutes=60,
            status="published",
        )
        self.other_exam_config = ExamConfig.objects.create(
            title="Knowledge Test Two",
            qualification=self.other_qualification,
            questions_per_exam=1,
            time_limit_minutes=90,
            status="published",
        )
        self.enrollment = Enrollment.objects.create(
            learner=self.profile,
            qualification=self.qualification,
            cohort="2026",
            employer="Old Employer",
            status=EnrollmentStatus.ACTIVE,
        )
        self.session = ExamSession.objects.create(
            exam_config=self.exam_config,
            learner=self.learner,
            invigilator=self.invigilator,
            scheduled_date=date(2026, 6, 1),
            scheduled_time=time(9, 0),
            allow_immediate_start=False,
            pin="123456",
            pin_active=True,
            status="scheduled",
        )

        self.client.force_authenticate(user=self.admin)
        self.url = reverse("learner-detail", kwargs={"user_id": self.learner.id})

    def test_partial_update_changes_profile_enrollment_and_session(self):
        response = self.client.patch(
            self.url,
            {
                "firstName": "New",
                "phone": "01999999999",
                "qualificationId": str(self.other_qualification.id),
                "cohort": "2027",
                "knowledgeTestId": str(self.other_exam_config.id),
                "invigilatorId": str(self.other_invigilator.id),
                "testDate": "2026-07-02",
                "testTime": "14:30:00",
                "allowImmediateStart": True,
                "pin": "654321",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.learner.refresh_from_db()
        self.profile.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.session.refresh_from_db()

        self.assertEqual(self.learner.first_name, "New")
        self.assertEqual(self.profile.phone, "01999999999")
        self.assertEqual(self.enrollment.qualification_id, self.other_qualification.id)
        self.assertEqual(self.enrollment.cohort, "2027")
        self.assertEqual(self.session.exam_config_id, self.other_exam_config.id)
        self.assertEqual(self.session.invigilator_id, self.other_invigilator.id)
        self.assertEqual(self.session.scheduled_date.isoformat(), "2026-07-02")
        self.assertEqual(self.session.scheduled_time.isoformat(), "14:30:00")
        self.assertTrue(self.session.allow_immediate_start)
        self.assertEqual(self.session.pin, "654321")
        self.assertIsNotNone(self.session.pin_window_start)
        self.assertIsNotNone(self.session.pin_window_end)

    def test_partial_update_rejects_session_changes_without_scheduled_session(self):
        self.session.status = "completed"
        self.session.save(update_fields=["status"])

        response = self.client.patch(
            self.url,
            {"knowledgeTestId": str(self.other_exam_config.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("knowledgeTestId", response.data["errors"])
