from datetime import date, time, timedelta

from django.utils import timezone

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.exams.models import ExamConfig, ExamResult, ExamSession, RetakeRequest
from apps.learners.models import Enrollment, EnrollmentStatus
from apps.qualifications.models import Level, Qualification, Sector
from apps.questions.models import Question
from apps.users.models import Role, User


class RetakeResitFlowTests(APITestCase):
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
            last_name="Gill",
            role=Role.INVIGILATOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="LearnerPass123!",
            first_name="Lina",
            last_name="Moon",
            role=Role.LEARNER,
        )

        self.level = Level.objects.create(name="level-3")
        self.sector = Sector.objects.create(name="Business", code="BUS")
        self.qualification = Qualification.objects.create(
            code="QUAL-BUS",
            title="Business Qualification",
            sector=self.sector,
            level=self.level,
            is_active=True,
        )
        self.exam_config = ExamConfig.objects.create(
            title="Business Live Exam",
            qualification=self.qualification,
            questions_per_exam=2,
            time_limit_minutes=60,
            grade_pass=60,
            status="published",
        )
        self.enrollment = Enrollment.objects.create(
            learner=self.learner.learner_profile,
            qualification=self.qualification,
            cohort="2026-Spring",
            status=EnrollmentStatus.ACTIVE,
        )
        Question.objects.create(
            qualification=self.qualification,
            question_text="Question 1",
            question_type="single",
            options=["A", "B"],
            correct_answers=[0],
            created_by=self.admin,
        )
        Question.objects.create(
            qualification=self.qualification,
            question_text="Question 2",
            question_type="single",
            options=["A", "B"],
            correct_answers=[1],
            created_by=self.admin,
        )
        Question.objects.create(
            qualification=self.qualification,
            question_text="Question 3",
            question_type="single",
            options=["A", "B"],
            correct_answers=[0],
            created_by=self.admin,
        )
        Question.objects.create(
            qualification=self.qualification,
            question_text="Question 4",
            question_type="single",
            options=["A", "B"],
            correct_answers=[1],
            created_by=self.admin,
        )
        self.question_ids = [
            str(q.id)
            for q in Question.objects.filter(qualification=self.qualification).order_by("created_at")
        ]

        self.previous_session = ExamSession.objects.create(
            exam_config=self.exam_config,
            enrollment=self.enrollment,
            learner=self.learner,
            invigilator=self.invigilator,
            scheduled_date=date(2026, 5, 20),
            scheduled_time=time(9, 0),
            pin="123456",
            pin_active=True,
            status="completed",
            question_set=[],
        )
        self.previous_result = ExamResult.objects.create(
            session=self.previous_session,
            learner=self.learner,
            exam_config=self.exam_config,
            qualification=self.qualification,
            score_percent=55,
            correct_count=1,
            total_questions=2,
            grade="did_not_pass",
            passed=False,
            time_taken_seconds=1500,
            violation_count=0,
            invigilator_name="Ivy Gill",
            reasonable_adjustments="",
            attempt_number=1,
            exam_date=date(2026, 5, 20),
        )
        self.retake_request = RetakeRequest.objects.create(
            learner=self.learner,
            exam_config=self.exam_config,
            previous_result=self.previous_result,
            status="pending",
        )

    def test_resit_endpoint_approves_pending_retake_and_links_session(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            reverse("retake-resit"),
            {
                "previous_result_id": str(self.previous_result.id),
                "invigilator_id": str(self.invigilator.id),
                "scheduled_date": "2026-05-22",
                "scheduled_time": "10:30:00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.retake_request.refresh_from_db()
        self.assertEqual(self.retake_request.status, "approved")
        self.assertEqual(self.retake_request.reviewed_by_id, self.admin.id)
        self.assertIsNotNone(self.retake_request.reviewed_at)
        self.assertIsNotNone(self.retake_request.new_session_id)
        self.assertEqual(str(self.retake_request.new_session_id), response.data["data"]["id"])
        self.assertEqual(self.retake_request.new_session.scheduled_date.isoformat(), "2026-05-22")
        self.assertEqual(self.retake_request.new_session.scheduled_time.isoformat(), "10:30:00")

    def test_retake_list_returns_schedule_and_reviewer_fields(self):
        self.client.force_authenticate(self.admin)
        self.retake_request.status = "approved"
        self.retake_request.reviewed_by = self.admin
        self.retake_request.new_session = ExamSession.objects.create(
            exam_config=self.exam_config,
            enrollment=self.enrollment,
            learner=self.learner,
            invigilator=self.invigilator,
            scheduled_date=date(2026, 5, 23),
            scheduled_time=time(11, 15),
            pin="654321",
            pin_active=True,
            status="scheduled",
            question_set=[],
        )
        self.retake_request.save(update_fields=["status", "reviewed_by", "new_session"])

        response = self.client.get(
            reverse("retake-list"),
            {"status": "approved", "previous_result_id": str(self.previous_result.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.data["results"][0]
        self.assertEqual(row["reviewed_by"], str(self.admin.id))
        self.assertEqual(row["reviewer_name"], "Admin User")
        self.assertEqual(row["new_session_id"], str(self.retake_request.new_session_id))
        self.assertEqual(row["scheduled_date"], "2026-05-23")
        self.assertEqual(row["scheduled_time"], "11:15:00")

    def test_retake_list_orders_by_latest_activity_newest_first(self):
        self.client.force_authenticate(self.admin)

        older_approved = RetakeRequest.objects.create(
            learner=self.learner,
            exam_config=self.exam_config,
            previous_result=self.previous_result,
            status="approved",
            reviewed_by=self.admin,
            reviewed_at=timezone.now() - timedelta(days=2),
        )
        newer_pending = self.retake_request
        newer_pending.requested_at = timezone.now() - timedelta(days=1)
        newer_pending.save(update_fields=["requested_at"])

        response = self.client.get(reverse("retake-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids[0], str(newer_pending.id))
        self.assertEqual(ids[1], str(older_approved.id))

    def test_flagged_questions_endpoint_returns_mapped_questions(self):
        self.client.force_authenticate(self.admin)
        self.previous_session.question_set = self.question_ids
        self.previous_session.draft_flagged_question_indexes = [1, 3]
        self.previous_session.save(update_fields=["question_set", "draft_flagged_question_indexes"])

        response = self.client.get(
            reverse("exam-session-flagged-questions", kwargs={"pk": self.previous_session.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["flagged_question_indexes"],
            [1, 3],
        )
        self.assertEqual(len(response.data["data"]["flagged_questions"]), 2)
        self.assertEqual(response.data["data"]["flagged_questions"][0]["index"], 1)
        self.assertEqual(response.data["data"]["flagged_questions"][0]["question_text"], "Question 2")
        self.assertEqual(response.data["data"]["flagged_questions"][1]["index"], 3)
        self.assertEqual(response.data["data"]["flagged_questions"][1]["question_text"], "Question 4")
