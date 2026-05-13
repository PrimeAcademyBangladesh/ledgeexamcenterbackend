from datetime import date, time

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.exams.models import ExamConfig, ExamSession
from apps.learners.models import Enrollment, EnrollmentStatus, ReasonableAdjustment
from apps.questions.models import Question
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
        self.assertIn("completed", response.data["errors"]["knowledgeTestId"])

    def test_partial_update_allows_blank_test_date_for_immediate_start(self):
        response = self.client.patch(
            self.url,
            {
                "knowledgeTestId": str(self.other_exam_config.id),
                "invigilatorId": str(self.other_invigilator.id),
                "testDate": "",
                "testTime": "14:30:00.000Z",
                "allowImmediateStart": True,
                "pin": "654321",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.session.refresh_from_db()
        self.assertEqual(self.session.exam_config_id, self.other_exam_config.id)
        self.assertEqual(self.session.invigilator_id, self.other_invigilator.id)
        self.assertTrue(self.session.allow_immediate_start)
        self.assertEqual(self.session.pin, "654321")

    def test_partial_update_rejects_non_active_enrollment_changes(self):
        self.enrollment.status = EnrollmentStatus.COMPLETED
        self.enrollment.save(update_fields=["status"])

        response = self.client.patch(
            self.url,
            {
                "qualificationId": str(self.other_qualification.id),
                "cohort": "2028",
                "employer": "updated employer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("qualificationId", response.data["errors"])
        self.assertIn("completed", response.data["errors"]["qualificationId"])


class LearnerRegistrationImmediateStartTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin-register@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="invigilator-register@example.com",
            password="InvigilatorPass123!",
            first_name="Ivy",
            last_name="Gilator",
            role=Role.INVIGILATOR,
        )
        self.level = Level.objects.create(name="level-5")
        self.sector = Sector.objects.create(name="Construction", code="CONST")
        self.qualification = Qualification.objects.create(
            code="QUAL-REG",
            title="Qualification Registration",
            sector=self.sector,
            level=self.level,
            is_active=True,
        )
        self.exam_config = ExamConfig.objects.create(
            title="Registration Exam",
            qualification=self.qualification,
            questions_per_exam=1,
            time_limit_minutes=60,
            status="published",
        )
        Question.objects.create(
            qualification=self.qualification,
            question_text="What does EPAO stand for?",
            question_type="single",
            options=[
                "End Point Assessment Organisation",
                "Education Provider Award Office",
            ],
            correct_answers=[0],
            created_by=self.admin,
        )
        self.client.force_authenticate(user=self.admin)

    def test_create_allows_blank_test_date_for_immediate_start(self):
        response = self.client.post(
            reverse("learner-list"),
            {
                "firstName": "Now",
                "lastName": "Learner",
                "email": "now-learner@example.com",
                "uln": "1175871922",
                "password": "Welcome123!",
                "dateOfBirth": "2000-05-05",
                "phone": "01234567890",
                "qualificationId": str(self.qualification.id),
                "cohort": "spring 2026",
                "employer": "hasan",
                "knowledgeTestId": str(self.exam_config.id),
                "invigilatorId": str(self.invigilator.id),
                "testDate": "",
                "testTime": "09:00:00.000Z",
                "allowImmediateStart": True,
                "pin": "123456",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])


class LearnerListContractTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin-list@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
        )
        self.invigilator = User.objects.create_user(
            email="invigilator-list@example.com",
            password="InvigilatorPass123!",
            first_name="Ivy",
            last_name="Gilator",
            role=Role.INVIGILATOR,
        )
        learner = User.objects.create_user(
            email="learner-list@example.com",
            password="LearnerPass123!",
            first_name="Aothy",
            last_name="Moon",
            role=Role.LEARNER,
        )
        profile = learner.learner_profile
        profile.uln = "1234567890"
        profile.date_of_birth = date(2000, 5, 5)
        profile.save()

        level = Level.objects.create(name="level-3")
        sector = Sector.objects.create(name="Business", code="BUS")
        qualification = Qualification.objects.create(
            code="QUAL-LIST",
            title="Construction Quesss",
            sector=sector,
            level=level,
            is_active=True,
        )
        exam_config = ExamConfig.objects.create(
            title="Test Exam by Moon",
            qualification=qualification,
            questions_per_exam=1,
            time_limit_minutes=60,
            status="published",
        )
        Enrollment.objects.create(
            learner=profile,
            qualification=qualification,
            cohort="spring 2026",
            employer="hasan",
            status=EnrollmentStatus.ACTIVE,
        )
        ExamSession.objects.create(
            exam_config=exam_config,
            learner=learner,
            invigilator=self.invigilator,
            scheduled_date=date(2026, 7, 2),
            scheduled_time=time(14, 30),
            allow_immediate_start=True,
            pin="654321",
            pin_active=True,
            status="scheduled",
        )

        self.client.force_authenticate(user=self.admin)

    def test_list_returns_frontend_envelope_and_registration_fields(self):
        response = self.client.get(reverse("learner-list"), {"page": 1, "page_size": 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        self.assertEqual(response.data["data"]["count"], 1)
        learner = response.data["data"]["results"][0]
        self.assertEqual(learner["qualificationName"], "Construction Quesss")
        self.assertEqual(learner["cohort"], "spring 2026")
        self.assertEqual(learner["employer"], "hasan")
        self.assertEqual(learner["testDate"], "2026-07-02")
        self.assertEqual(learner["testTime"], "14:30:00")
        self.assertTrue(learner["allowImmediateStart"])
        self.assertEqual(learner["pin"], "654321")


class ReasonableAdjustmentListPaginationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin2@example.com",
            password="AdminPass123!",
            first_name="Admin",
            last_name="User",
            role=Role.ADMIN,
        )
        self.learner = User.objects.create_user(
            email="learner2@example.com",
            password="LearnerPass123!",
            first_name="Learner",
            last_name="User",
            role=Role.LEARNER,
        )
        self.profile = self.learner.learner_profile
        ReasonableAdjustment.objects.create(
            learner=self.profile,
            notes="Extra time",
            accepted=True,
            denied=False,
            extra_time_minutes=15,
            created_by=self.admin,
        )
        ReasonableAdjustment.objects.create(
            learner=self.profile,
            notes="Reader support",
            accepted=False,
            denied=False,
            extra_time_minutes=0,
            created_by=self.admin,
        )
        self.client.force_authenticate(user=self.admin)

    def test_list_uses_enveloped_pagination_fields(self):
        response = self.client.get(
            reverse("reasonable-adjustment-list"),
            {"learnerId": str(self.learner.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(len(response.data["results"]), 2)
