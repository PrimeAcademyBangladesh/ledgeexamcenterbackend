"""
Reusable services for the Exams app.

The question-selection service is the single source of truth for picking
questions. It is used by:
  * Scheduled session creation        (admin)
  * Resit session creation            (invigilator/admin)
  * Mock-exam start                   (learner — does NOT mark as seen)
"""

import random
from datetime import datetime, timedelta, timezone as dt_tz
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from questions.models import Question
from .models import ExamConfig, ExamSession, LearnerSeenQuestion


# ---------------------------------------------------------------------------
# Question selection
# ---------------------------------------------------------------------------
def select_questions_for_learner(*, exam_config: ExamConfig, learner, mark_seen_session=None):
    """
    Returns a list of Question objects of size exam_config.questions_per_exam,
    excluding any question already in LearnerSeenQuestion for this learner.

    If `mark_seen_session` is provided, also creates LearnerSeenQuestion rows
    inside the same transaction. Pass None for mock/practice exams.
    """
    qualification = exam_config.qualification
    required_count = exam_config.questions_per_exam

    seen_qids = set(
        LearnerSeenQuestion.objects.filter(
            learner=learner, qualification=qualification
        ).values_list("question_id", flat=True)
    )

    pool = list(
        Question.objects.filter(
            qualification=qualification, is_active=True
        ).exclude(id__in=seen_qids).values_list("id", flat=True)
    )

    if len(pool) < required_count:
        raise ValidationError(
            "Not enough unseen questions available. Add more questions to "
            "this qualification before creating this session."
        )

    chosen_ids = random.sample(pool, required_count)
    chosen = list(Question.objects.filter(id__in=chosen_ids))
    # Preserve the random order chosen (filter() does not guarantee it)
    order_index = {qid: i for i, qid in enumerate(chosen_ids)}
    chosen.sort(key=lambda q: order_index[q.id])

    if mark_seen_session is not None:
        LearnerSeenQuestion.objects.bulk_create(
            [
                LearnerSeenQuestion(
                    learner=learner,
                    qualification=qualification,
                    question=q,
                    session=mark_seen_session,
                )
                for q in chosen
            ],
            ignore_conflicts=True,
        )

    return chosen


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------
def _generate_pin() -> str:
    return f"{random.randint(0, 999_999):06d}"


def _compute_pin_window(scheduled_date, scheduled_time, exam_config, extra_minutes=0):
    start_dt = datetime.combine(
        scheduled_date, scheduled_time, tzinfo=dt_tz.utc
    )
    return (
        start_dt - timedelta(minutes=5),
        start_dt + timedelta(minutes=exam_config.time_limit_minutes + (extra_minutes or 0)),
    )


@transaction.atomic
def create_scheduled_session(
    *, exam_config, learner, invigilator,
    scheduled_date, scheduled_time,
    pin=None, allow_immediate_start=False,
    reasonable_adjustments="", extra_time_minutes=None,
    previous_result=None,
):
    pin_start, pin_end = _compute_pin_window(
        scheduled_date, scheduled_time, exam_config, extra_time_minutes or 0
    )

    session = ExamSession.objects.create(
        exam_config=exam_config,
        learner=learner,
        invigilator=invigilator,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        pin_window_start=pin_start,
        pin_window_end=pin_end,
        allow_immediate_start=allow_immediate_start,
        pin=pin or _generate_pin(),
        pin_active=True,
        reasonable_adjustments=reasonable_adjustments or "",
        extra_time_minutes=extra_time_minutes,
        previous_result=previous_result,
        status="scheduled",
    )

    chosen = select_questions_for_learner(
        exam_config=exam_config, learner=learner, mark_seen_session=session
    )
    session.question_set = [str(q.id) for q in chosen]
    session.save(update_fields=["question_set"])

    # Hard assertions — fail loud if invariants break
    assert len(session.question_set) == exam_config.questions_per_exam
    return session


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_submission(*, session: ExamSession, answers: list[dict]) -> dict:
    """
    answers: [{questionId: str, selected: [int]}]
    Returns dict with score_percent, correct_count, grade, passed.
    """
    cfg = session.exam_config
    questions = {
        str(q.id): q for q in
        __import__("questions").models.Question.objects.filter(
            id__in=session.question_set
        )
    }

    correct = 0
    for a in answers:
        q = questions.get(a["questionId"])
        if not q:
            continue
        if sorted(a.get("selected", [])) == sorted(q.correct_answers or []):
            correct += 1

    total = len(session.question_set)
    pct = round((correct / total) * 100) if total else 0

    if pct >= cfg.grade_distinction:
        grade = "distinction"
    elif pct >= cfg.grade_merit:
        grade = "merit"
    elif pct >= cfg.grade_pass:
        grade = "pass"
    else:
        grade = "did_not_pass"

    return {
        "score_percent": pct,
        "correct_count": correct,
        "total_questions": total,
        "grade": grade,
        "passed": pct >= cfg.grade_pass,
    }


# ---------------------------------------------------------------------------
# Resit eligibility (mirrors src/services/api/retakes.ts isResitEligible)
# ---------------------------------------------------------------------------
def is_resit_eligible(score_percent: int, pass_mark: int) -> bool:
    return score_percent < pass_mark and score_percent >= (pass_mark - 10)
