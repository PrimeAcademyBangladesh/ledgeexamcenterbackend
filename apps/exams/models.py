"""
Lead Edge Ltd — Exams app models
=================================
Aligned with the React UI (ExamConfig, ExamSession, ExamResult, IntegrityViolation,
RetakeRequest, ExamDraft, LearnerSeenQuestion).

Naming convention:
- Python/DB fields are snake_case (Django convention).
- The React app speaks camelCase. Conversion happens in the global Axios
  interceptor (src/services/api/client.ts) AND/OR via
  djangorestframework-camel-case renderers — pick one, do not double-convert.

Key invariants enforced here:
- ExamSession.question_set is the FROZEN paper for that session.
- LearnerSeenQuestion has a UNIQUE (learner, question) constraint to block
  duplicate delivery at the database level.
- PIN is a 6-digit string, never an int (preserves leading zeros).
- Resit window is computed from ExamConfig.grade_pass at runtime, not stored.
"""

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# ExamConfig
# ---------------------------------------------------------------------------
class ExamConfig(models.Model):
    EXAM_TYPE_CHOICES = [("live", "Live"), ("mock", "Mock")]
    STATUS_CHOICES = [("draft", "Draft"), ("published", "Published")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    version_number = models.CharField(max_length=10, default="v1.0")
    qualification = models.ForeignKey(
        "qualifications.Qualification",
        on_delete=models.PROTECT,
        related_name="exam_configs",
    )
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPE_CHOICES, default="live")

    questions_per_exam = models.PositiveIntegerField()
    time_limit_minutes = models.PositiveIntegerField()

    shuffle_questions = models.BooleanField(default=True)
    shuffle_options = models.BooleanField(default=True)
    strict_mode = models.BooleanField(default=True)

    # Scenario configuration — list of group rules.
    # Each entry: {"count": int, "questions_per_scenario": int}
    # Empty list (default) means no scenarios — all questions are standalone.
    # Example: [{"count": 4, "questions_per_scenario": 10}] = 4 groups × 10 = 40 questions.
    scenario_rules = models.JSONField(default=list, blank=True)

    grade_distinction = models.PositiveSmallIntegerField(default=85)
    grade_merit = models.PositiveSmallIntegerField(default=70)
    grade_pass = models.PositiveSmallIntegerField(default=60)

    # Certification validity — how long a pass is valid after the exam date.
    # null = not configured (no cert expiry shown).
    # 0    = no expiry (permanent certification).
    # 12   = 1 year, 24 = 2 years, 36 = 3 years, etc.
    cert_validity_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Certificate validity in months. 0 = no expiry. Null = not set.",
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.version_number})"




# ---------------------------------------------------------------------------
# ExamSession  (one scheduled attempt for one learner)
# ---------------------------------------------------------------------------
class ExamSession(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam_config = models.ForeignKey(
        ExamConfig, on_delete=models.PROTECT, related_name="sessions"
    )
    enrollment = models.ForeignKey(
        "learners.Enrollment",
        on_delete=models.PROTECT,
        related_name="exam_sessions",
        null=True,
        blank=True,
    )
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exam_sessions_as_learner",
        limit_choices_to={"role": "learner"},
    )
    invigilator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exam_sessions_as_invigilator",
        limit_choices_to={"role": "invigilator"},
    )

    # Schedule + PIN window (UI shows pinWindowStart/pinWindowEnd as ISO strings)
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    pin_window_start = models.DateTimeField(null=True, blank=True)
    pin_window_end = models.DateTimeField(null=True, blank=True)
    allow_immediate_start = models.BooleanField(default=False)

    pin = models.CharField(max_length=6)  # always 6 numeric chars, leading zeros preserved
    pin_active = models.BooleanField(default=True)

    # Frozen paper for this session — set once, server-side only.
    # Stored as ordered list of Question UUIDs (strings). Order is preserved
    # through to the learner UI; only shuffling on first delivery is allowed.
    question_set = models.JSONField(default=list, blank=True)

    # Frozen scenario content keyed by scenario UUID (str).
    # Built at session creation from the live Scenario rows; immutable after that.
    # Shape: {"<uuid>": {"title": str, "body": str, "imageUrl": str|null}}
    scenario_snapshot = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="scheduled")

    # Invigilator workflow flags
    id_verified = models.BooleanField(default=False)
    completed_successfully = models.BooleanField(null=True, blank=True)
    incident_notes = models.TextField(blank=True, default="")

    # Reasonable adjustments snapshot (so changes to RA later don't alter history)
    reasonable_adjustments = models.TextField(blank=True, default="")
    extra_time_minutes = models.PositiveIntegerField(null=True, blank=True)

    # Resume / autosave fields  (one row per session; no separate Draft table)
    draft_answers = models.JSONField(default=list, blank=True)              # [{questionId, selected:[int]}]
    draft_current_question_index = models.PositiveIntegerField(default=0)
    draft_flagged_question_indexes = models.JSONField(default=list, blank=True)
    draft_remaining_seconds = models.PositiveIntegerField(null=True, blank=True)
    draft_updated_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Provenance for resits
    previous_result = models.ForeignKey(
        "ExamResult",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="resit_sessions",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_date", "scheduled_time"]
        indexes = [
            models.Index(fields=["enrollment", "status"]),
            models.Index(fields=["learner", "status"]),
            models.Index(fields=["invigilator", "scheduled_date"]),
        ]

    def __str__(self):
        return f"{self.exam_config.title} — {self.learner} @ {self.scheduled_date} {self.scheduled_time}"


# ---------------------------------------------------------------------------
# LearnerSeenQuestion  (single source of truth for "already delivered")
# ---------------------------------------------------------------------------
class LearnerSeenQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seen_questions",
        limit_choices_to={"role": "learner"},
    )
    qualification = models.ForeignKey(
        "qualifications.Qualification",
        on_delete=models.CASCADE,
        related_name="seen_question_records",
    )
    question = models.ForeignKey(
        "questions.Question",
        on_delete=models.CASCADE,
        related_name="seen_records",
    )
    session = models.ForeignKey(
        ExamSession,
        on_delete=models.CASCADE,
        related_name="seen_question_records",
    )
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "question"],
                name="unique_seen_question_per_learner",
            ),
        ]
        indexes = [
            models.Index(fields=["learner", "qualification"]),
        ]


# ---------------------------------------------------------------------------
# LearnerSeenScenario  (prevents same scenario being served twice)
# ---------------------------------------------------------------------------
class LearnerSeenScenario(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seen_scenarios",
        limit_choices_to={"role": "learner"},
    )
    scenario = models.ForeignKey(
        "questions.Scenario",
        on_delete=models.CASCADE,
        related_name="seen_records",
    )
    session = models.ForeignKey(
        ExamSession,
        on_delete=models.CASCADE,
        related_name="seen_scenario_records",
    )
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "scenario"],
                name="unique_seen_scenario_per_learner",
            ),
        ]
        indexes = [
            models.Index(fields=["learner"]),
        ]


# ---------------------------------------------------------------------------
# IntegrityViolation
# ---------------------------------------------------------------------------
class IntegrityViolation(models.Model):
    VIOLATION_TYPES = [
        ("tab_switch", "Tab Switch"),
        ("fullscreen_exit", "Fullscreen Exit"),
        ("right_click", "Right Click"),
        ("copy_paste", "Copy/Paste"),
        ("devtools", "DevTools"),
        ("print_attempt", "Print Attempt"),
        ("time_exceeded", "Time Exceeded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ExamSession, on_delete=models.CASCADE, related_name="violations"
    )
    type = models.CharField(max_length=30, choices=VIOLATION_TYPES)
    detail = models.CharField(max_length=255)
    question_number = models.PositiveIntegerField()
    occurred_at = models.DateTimeField(default=timezone.now)


# ---------------------------------------------------------------------------
# ExamResult
# ---------------------------------------------------------------------------
class ExamResult(models.Model):
    GRADE_CHOICES = [
        ("distinction", "Distinction"),
        ("merit", "Merit"),
        ("pass", "Pass"),
        ("did_not_pass", "Did Not Pass"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        ExamSession, on_delete=models.PROTECT, related_name="result"
    )
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exam_results",
    )
    exam_config = models.ForeignKey(ExamConfig, on_delete=models.PROTECT)
    qualification = models.ForeignKey(
        "qualifications.Qualification", on_delete=models.PROTECT
    )

    score_percent = models.PositiveSmallIntegerField()
    correct_count = models.PositiveIntegerField()
    total_questions = models.PositiveIntegerField()
    grade = models.CharField(max_length=20, choices=GRADE_CHOICES)
    passed = models.BooleanField()

    time_taken_seconds = models.PositiveIntegerField()
    violation_count = models.PositiveIntegerField(default=0)

    # Snapshot of the frozen paper actually delivered
    question_ids = models.JSONField(default=list, blank=True)
    # Snapshot of submitted answers for audit / regrade
    answers = models.JSONField(default=list, blank=True)

    invigilator_name = models.CharField(max_length=255, blank=True, default="")
    reasonable_adjustments = models.TextField(blank=True, default="")
    attempt_number = models.PositiveSmallIntegerField(default=1)

    exam_date = models.DateField()
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["learner", "exam_config"]),
            models.Index(fields=["qualification", "submitted_at"]),
        ]


# ---------------------------------------------------------------------------
# RetakeRequest  (learner-initiated; resits are invigilator-created sessions)
# ---------------------------------------------------------------------------
class RetakeRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("denied", "Denied"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="retake_requests",
    )
    exam_config = models.ForeignKey(ExamConfig, on_delete=models.PROTECT)
    previous_result = models.ForeignKey(
        ExamResult, on_delete=models.PROTECT, related_name="retake_requests"
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="reviewed_retakes",
    )
    denial_reason = models.TextField(blank=True, default="")
    new_session = models.ForeignKey(
        ExamSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="from_retake_request",
    )

    class Meta:
        constraints = [
            # Block duplicate pending requests for the same prior result
            models.UniqueConstraint(
                fields=["previous_result"],
                condition=models.Q(status="pending"),
                name="unique_pending_retake_per_result",
            ),
        ]
        ordering = ["-requested_at"]
