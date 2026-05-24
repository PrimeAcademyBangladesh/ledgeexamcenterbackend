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

from apps.questions.models import Question, Scenario
from .models import ExamConfig, ExamResult, ExamSession, LearnerSeenQuestion, LearnerSeenScenario


# ---------------------------------------------------------------------------
# Question selection
# ---------------------------------------------------------------------------
def select_questions_for_learner(*, exam_config: ExamConfig, learner, mark_seen_session=None):
    """
    Returns (questions, scenario_snapshot) where:
      - questions        is an ordered list of Question objects
      - scenario_snapshot is a dict {str(scenario_id): {title, body, imageUrl}}

    Scenario-aware logic (when exam_config.scenario_rules is non-empty):
      1. For each rule {"count": N, "questions_per_scenario": K}:
         - Pick N unseen eligible scenarios (must have >= K active questions).
         - Take exactly K questions per scenario in scenario_order.
         - Groups themselves are shuffled if shuffle_questions=True.
      2. Fill remaining slots with standalone questions (scenario=None).

    If mark_seen_session is provided, LearnerSeenQuestion and
    LearnerSeenScenario rows are written inside the same transaction.
    Pass None for mock/practice exams.
    """
    if mark_seen_session is not None:
        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError("Persisted question selection must run inside transaction.atomic().")
        learner = learner.__class__.objects.select_for_update().get(pk=learner.pk)

    qualification = exam_config.qualification
    required_count = exam_config.questions_per_exam
    scenario_rules = exam_config.scenario_rules or []

    # ── Seen sets ────────────────────────────────────────────────────────────
    seen_qids = set(
        LearnerSeenQuestion.objects.filter(
            learner=learner, qualification=qualification
        ).values_list("question_id", flat=True)
    )
    seen_scenario_ids = set(
        LearnerSeenScenario.objects.filter(learner=learner)
        .values_list("scenario_id", flat=True)
    )

    scenario_groups = []      # list of list[Question], in final display order
    scenario_snapshot = {}    # {str(uuid): {title, body, imageUrl}}
    total_scenario_q_count = 0

    # ── Phase 1: Scenario groups ─────────────────────────────────────────────
    for rule in scenario_rules:
        group_count = rule["count"]
        q_per_scenario = rule["questions_per_scenario"]
        total_scenario_q_count += group_count * q_per_scenario

        # Eligible scenarios: active, unseen, belonging to this qualification,
        # with enough active questions.
        eligible_scenarios = [
            s for s in Scenario.objects.filter(
                qualification=qualification, status="active"
            ).exclude(id__in=seen_scenario_ids)
            if s.active_question_count >= q_per_scenario
        ]

        if len(eligible_scenarios) < group_count:
            raise ValidationError(
                f"Not enough unseen eligible scenarios available "
                f"(need {group_count}, found {len(eligible_scenarios)}). "
                f"Add more scenarios to this qualification before creating this session."
            )

        chosen_scenarios = random.sample(eligible_scenarios, group_count)

        # Shuffle group order if configured
        if exam_config.shuffle_questions:
            random.shuffle(chosen_scenarios)

        for scenario in chosen_scenarios:
            # Take questions in scenario_order; exclude any already seen
            qs = list(
                Question.objects.filter(
                    scenario=scenario, is_active=True
                ).exclude(id__in=seen_qids)
                .order_by("scenario_order")[:q_per_scenario]
            )
            if len(qs) < q_per_scenario:
                raise ValidationError(
                    f"Scenario '{scenario.title}' does not have enough unseen questions "
                    f"(need {q_per_scenario}, found {len(qs)})."
                )
            scenario_groups.append(qs)
            seen_scenario_ids.add(scenario.id)

            # Build snapshot entry (image path only — no request context here;
            # the view layer converts to absolute URL when serialising)
            snapshot_entry = {
                "title": scenario.title,
                "body": scenario.body,
                "imagePath": scenario.image.name if scenario.image else None,
            }
            scenario_snapshot[str(scenario.id)] = snapshot_entry

            # Update running seen set so we don't accidentally re-pick
            for q in qs:
                seen_qids.add(q.id)

    # ── Phase 2: Standalone questions ────────────────────────────────────────
    standalone_needed = required_count - total_scenario_q_count
    chosen_standalone = []

    if standalone_needed > 0:
        standalone_pool = list(
            Question.objects.filter(
                qualification=qualification,
                is_active=True,
                scenario__isnull=True,
            ).exclude(id__in=seen_qids).values_list("id", flat=True)
        )

        if len(standalone_pool) < standalone_needed:
            raise ValidationError(
                f"Not enough unseen standalone questions available "
                f"(need {standalone_needed}, found {len(standalone_pool)}). "
                f"Add more questions to this qualification before creating this session."
            )

        standalone_ids = random.sample(standalone_pool, standalone_needed)
        chosen_standalone = list(Question.objects.filter(id__in=standalone_ids))
        # Restore random order (filter() does not guarantee it)
        order_index = {qid: i for i, qid in enumerate(standalone_ids)}
        chosen_standalone.sort(key=lambda q: order_index[q.id])

    # ── Phase 3: Assemble final ordered list ─────────────────────────────────
    # Scenario groups come first (already shuffled above if configured),
    # then standalone questions.
    all_questions = []
    for group in scenario_groups:
        all_questions.extend(group)
    all_questions.extend(chosen_standalone)

    assert len(all_questions) == required_count, (
        f"Question count mismatch: assembled {len(all_questions)}, expected {required_count}"
    )

    # ── Phase 4: Persist seen records ────────────────────────────────────────
    if mark_seen_session is not None:
        LearnerSeenQuestion.objects.bulk_create(
            [
                LearnerSeenQuestion(
                    learner=learner,
                    qualification=qualification,
                    question=q,
                    session=mark_seen_session,
                )
                for q in all_questions
            ],
            ignore_conflicts=True,
        )

        # Record each scenario as seen
        scenario_ids_to_mark = list(scenario_snapshot.keys())
        if scenario_ids_to_mark:
            scenario_objs = Scenario.objects.filter(id__in=scenario_ids_to_mark)
            LearnerSeenScenario.objects.bulk_create(
                [
                    LearnerSeenScenario(
                        learner=learner,
                        scenario=s,
                        session=mark_seen_session,
                    )
                    for s in scenario_objs
                ],
                ignore_conflicts=True,
            )

    return all_questions, scenario_snapshot


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------
def _generate_pin() -> str:
    return f"{random.randint(0, 999_999):06d}"


def _compute_pin_window(
    scheduled_date, scheduled_time, exam_config,
    extra_minutes=0, allow_immediate_start=False,
):
    """
    Returns (pin_window_start, pin_window_end).

    Default:    [scheduled - 5min, scheduled + duration + extra]
    Sit-now:    [now,              now       + duration + extra]
                — the learner can use the PIN immediately; scheduled
                  date/time becomes informational only.
    """
    duration = timedelta(minutes=exam_config.time_limit_minutes + (extra_minutes or 0))
    if allow_immediate_start:
        start_dt = timezone.now()
        return start_dt, start_dt + duration
    start_dt = datetime.combine(scheduled_date, scheduled_time, tzinfo=dt_tz.utc)
    return start_dt - timedelta(minutes=5), start_dt + duration


@transaction.atomic
def create_scheduled_session(
    *, exam_config, learner, invigilator,
    scheduled_date, scheduled_time,
    enrollment=None,
    pin=None, allow_immediate_start=False,
    reasonable_adjustments="", extra_time_minutes=None,
    previous_result=None,
):
    if previous_result is not None:
        previous_result = ExamResult.objects.select_for_update().get(pk=previous_result.pk)
    exam_config = ExamConfig.objects.select_for_update().get(pk=exam_config.pk)

    pin_start, pin_end = _compute_pin_window(
        scheduled_date, scheduled_time, exam_config,
        extra_minutes=extra_time_minutes or 0,
        allow_immediate_start=allow_immediate_start,
    )

    session = ExamSession.objects.create(
        exam_config=exam_config,
        enrollment=enrollment,
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

    chosen, scenario_snapshot = select_questions_for_learner(
        exam_config=exam_config, learner=learner, mark_seen_session=session
    )
    session.question_set = [str(q.id) for q in chosen]
    session.scenario_snapshot = scenario_snapshot
    session.save(update_fields=["question_set", "scenario_snapshot"])

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
        str(q.id): q
        for q in Question.objects.filter(id__in=session.question_set)
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
