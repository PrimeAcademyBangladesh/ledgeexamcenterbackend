"""
Shared pytest fixtures for the Lead Edge exam platform test suite.

Hierarchy:
  sector → level → qualification → questions (x10)
  admin / invigilator / learner users  (signal auto-creates profiles)
  enrollment  (LearnerProfile → Qualification)
  exam_config (5 questions per exam, 60 min, pass=60)
  session     (scheduled 2026-05-21 10:00 Europe/London, PIN "123456")
"""

import datetime as dt
import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.users.models import User, LearnerProfile
from apps.qualifications.models import Qualification, Sector, Level
from apps.questions.models import Question
from apps.learners.models import Enrollment, EnrollmentStatus
from apps.exams.models import ExamConfig, ExamSession, ExamResult, LearnerSeenQuestion
from apps.exams.services import _compute_pin_window


# ─── Seed dates used across the suite ───────────────────────────────────────
EXAM_DATE = dt.date(2026, 5, 21)
EXAM_TIME = dt.time(10, 0, 0)           # 10:00 Europe/London (BST, UTC+1) = 09:00 UTC
# PIN window (localised correctly): 08:55 – 10:00 UTC
INSIDE_WINDOW = dt.datetime(2026, 5, 21, 8, 57, 0, tzinfo=dt.timezone.utc)
BEFORE_WINDOW = dt.datetime(2026, 5, 21, 8, 54, 0, tzinfo=dt.timezone.utc)   # 6 min early
AFTER_WINDOW  = dt.datetime(2026, 5, 21, 10, 1, 0, tzinfo=dt.timezone.utc)   # 1 min past end
AT_WINDOW_START = dt.datetime(2026, 5, 21, 8, 55, 0, tzinfo=dt.timezone.utc) # exactly T-5


# ─── Users ──────────────────────────────────────────────────────────────────
@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin.test@leadedge.test",
        password="admin@2020",
        first_name="Admin",
        last_name="User",
        role="admin",
        is_staff=True,
    )


@pytest.fixture
def invigilator_user(db):
    return User.objects.create_user(
        email="inv.test@leadedge.test",
        password="admin@2020",
        first_name="Inv",
        last_name="User",
        role="invigilator",
    )


@pytest.fixture
def invigilator_user2(db):
    return User.objects.create_user(
        email="inv2.test@leadedge.test",
        password="admin@2020",
        first_name="Inv2",
        last_name="User",
        role="invigilator",
    )


@pytest.fixture
def learner_user(db):
    # post_save signal auto-creates LearnerProfile
    return User.objects.create_user(
        email="learner.test@leadedge.test",
        password="admin@2020",
        first_name="Learner",
        last_name="User",
        role="learner",
    )


@pytest.fixture
def learner_user2(db):
    return User.objects.create_user(
        email="learner2.test@leadedge.test",
        password="admin@2020",
        first_name="Learner2",
        last_name="User",
        role="learner",
    )


# ─── Qualification hierarchy ─────────────────────────────────────────────────
@pytest.fixture
def sector(db):
    return Sector.objects.create(name="Business", code="BUS-TEST")


@pytest.fixture
def level(db):
    return Level.objects.create(name="level-3")


@pytest.fixture
def qualification(db, sector, level):
    return Qualification.objects.create(
        code="TEST-QUAL-001",
        title="Test Business Administration",
        sector=sector,
        level=level,
        default_questions_per_exam=5,
        default_time_limit_minutes=60,
        default_pass_boundary=50,
        default_merit_boundary=70,
        default_distinction_boundary=85,
        min_bank_size=10,
        recommended_bank_size=20,
    )


# ─── Questions ───────────────────────────────────────────────────────────────
@pytest.fixture
def questions(db, qualification, admin_user):
    """10 active questions so there's enough for a 5-question exam + resit."""
    qs = []
    for i in range(10):
        q = Question.objects.create(
            qualification=qualification,
            question_text=f"Test question {i + 1}?",
            question_type="single",
            options=["Option A", "Option B", "Option C", "Option D"],
            correct_answers=[0],
            is_active=True,
            created_by=admin_user,
        )
        qs.append(q)
    return qs


# ─── ExamConfig ──────────────────────────────────────────────────────────────
@pytest.fixture
def exam_config(db, qualification):
    return ExamConfig.objects.create(
        title="Test Exam Config",
        qualification=qualification,
        exam_type="live",
        questions_per_exam=5,
        time_limit_minutes=60,
        grade_distinction=85,
        grade_merit=70,
        grade_pass=60,
        status="published",
    )


# ─── Enrollment ──────────────────────────────────────────────────────────────
@pytest.fixture
def enrollment(db, learner_user, qualification):
    profile = LearnerProfile.objects.get(user=learner_user)
    return Enrollment.objects.create(
        learner=profile,
        qualification=qualification,
        cohort="2026-Spring",
        status=EnrollmentStatus.ACTIVE,
        enrolled_at=timezone.now(),
    )


@pytest.fixture
def enrollment2(db, learner_user2, qualification):
    profile = LearnerProfile.objects.get(user=learner_user2)
    return Enrollment.objects.create(
        learner=profile,
        qualification=qualification,
        cohort="2026-Spring",
        status=EnrollmentStatus.ACTIVE,
        enrolled_at=timezone.now(),
    )


# ─── ExamSession ─────────────────────────────────────────────────────────────
@pytest.fixture
def session(db, exam_config, learner_user, invigilator_user, enrollment, questions):
    """
    A fully-configured scheduled session for 2026-05-21 10:00 Europe/London (BST = 09:00 UTC).
    PIN window: 08:55 – 10:00 UTC.  PIN: "123456".
    question_set is the first 5 questions from the fixture.
    LearnerSeenQuestion rows are created to mirror production behaviour.
    """
    pin_start, pin_end = _compute_pin_window(EXAM_DATE, EXAM_TIME, exam_config)
    sess = ExamSession.objects.create(
        exam_config=exam_config,
        enrollment=enrollment,
        learner=learner_user,
        invigilator=invigilator_user,
        scheduled_date=EXAM_DATE,
        scheduled_time=EXAM_TIME,
        pin_window_start=pin_start,
        pin_window_end=pin_end,
        pin="123456",
        pin_active=True,
        status="scheduled",
        id_verified=True,
        question_set=[str(q.id) for q in questions[:5]],
    )
    LearnerSeenQuestion.objects.bulk_create(
        [
            LearnerSeenQuestion(
                learner=learner_user,
                qualification=exam_config.qualification,
                question=q,
                session=sess,
            )
            for q in questions[:5]
        ],
        ignore_conflicts=True,
    )
    return sess


@pytest.fixture
def in_progress_session(db, session):
    """session already flipped to in_progress with a started_at."""
    session.status = "in_progress"
    session.started_at = INSIDE_WINDOW
    session.save(update_fields=["status", "started_at"])
    return session


# ─── API Clients ─────────────────────────────────────────────────────────────
@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def invigilator_client(invigilator_user):
    c = APIClient()
    c.force_authenticate(user=invigilator_user)
    return c


@pytest.fixture
def learner_client(learner_user):
    c = APIClient()
    c.force_authenticate(user=learner_user)
    return c


@pytest.fixture
def learner2_client(learner_user2):
    c = APIClient()
    c.force_authenticate(user=learner_user2)
    return c


@pytest.fixture
def anon_client():
    return APIClient()


# ─── Helpers ─────────────────────────────────────────────────────────────────
def make_answers(question_ids, selected=None):
    """Build a valid answers list for all given question IDs."""
    return [
        {"questionId": str(qid), "selected": selected if selected is not None else [0]}
        for qid in question_ids
    ]
