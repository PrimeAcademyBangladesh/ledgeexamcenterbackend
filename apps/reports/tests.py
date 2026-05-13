from datetime import date, datetime, time, timezone

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.exams.models import ExamConfig, ExamResult, ExamSession
from apps.qualifications.models import Level, Qualification, Sector
from apps.users.models import Role, User


class ReportApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="reports-admin@example.com",
            password="AdminPass123!",
            first_name="Reports",
            last_name="Admin",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="reports-invigilator@example.com",
            password="InvigilatorPass123!",
            first_name="Ivy",
            last_name="Gilator",
            role=Role.INVIGILATOR,
        )
        self.learner = User.objects.create_user(
            email="reports-learner@example.com",
            password="LearnerPass123!",
            first_name="Aothy",
            last_name="Moon",
            role=Role.LEARNER,
        )
        learner_profile = self.learner.learner_profile
        learner_profile.uln = "1175871922"
        learner_profile.save()

        self.level = Level.objects.create(name="level-6")
        self.sector = Sector.objects.create(name="Business Reports", code="RPT")
        self.qualification = Qualification.objects.create(
            code="QUAL-RPT",
            title="Business Qualification",
            sector=self.sector,
            level=self.level,
            is_active=True,
        )
        self.exam_config = ExamConfig.objects.create(
            title="Knowledge Test",
            qualification=self.qualification,
            questions_per_exam=40,
            time_limit_minutes=60,
            status="published",
        )
        self.session = ExamSession.objects.create(
            exam_config=self.exam_config,
            learner=self.learner,
            invigilator=self.invigilator,
            scheduled_date=date(2026, 7, 2),
            scheduled_time=time(9, 0),
            pin="123456",
            pin_active=True,
            status="completed",
        )
        self.result = ExamResult.objects.create(
            session=self.session,
            learner=self.learner,
            exam_config=self.exam_config,
            qualification=self.qualification,
            score_percent=85,
            correct_count=34,
            total_questions=40,
            grade="distinction",
            passed=True,
            time_taken_seconds=3200,
            violation_count=1,
            invigilator_name="Ivy Gilator",
            reasonable_adjustments="Extra time",
            attempt_number=1,
            exam_date=date(2026, 7, 2),
            submitted_at=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        )
        self.client.force_authenticate(user=self.admin)

    def test_list_returns_rows_and_stats(self):
        response = self.client.get(reverse("report-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertEqual(len(response.data["data"]["rows"]), 1)
        row = response.data["data"]["rows"][0]
        self.assertEqual(row["learnerName"], "Aothy Moon")
        self.assertEqual(row["uln"], "1175871922")
        self.assertEqual(row["qualificationName"], "Business Qualification")
        self.assertEqual(row["examTitle"], "Knowledge Test")
        self.assertEqual(row["scorePercent"], 85)
        self.assertEqual(response.data["data"]["stats"]["totalAttempts"], 1)

    def test_list_filters_by_qualification(self):
        response = self.client.get(
            reverse("report-list"),
            {"qualification_id": str(self.qualification.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["count"], 1)

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(user=self.invigilator)
        response = self.client.get(reverse("report-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
