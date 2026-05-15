"""
apps/learners/models.py
────────────────────────────────────────────────────────────
Extends the LearnerProfile (defined in apps.users.models) with:

  • Enrollment              — Learner ↔ Qualification linkage
  • ReasonableAdjustment    — accommodations applied to sessions

Note: LearnerProfile itself lives in apps.users so it can be created
automatically by the post_save signal you already wrote.
"""

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def validate_reasonable_adjustment_state(*, accepted, denied, denial_reason) -> None:
    errors = {}
    if accepted and denied:
        errors["accepted"] = "Cannot be both accepted and denied."
    if not accepted and not denied:
        # A reasonable adjustment must be actioned at the moment it's recorded;
        # there is no "pending" state in the admin UI.
        errors["accepted"] = "Choose either Accepted or Denied."
    if denied and not (denial_reason or "").strip():
        errors["denial_reason"] = "Required when denying."
    if errors:
        raise ValidationError(errors)


# ─────────────────────────────────────────────────────────────
# Enrollment — Learner ↔ Qualification
# ─────────────────────────────────────────────────────────────

class EnrollmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    WITHDRAWN = "withdrawn", "Withdrawn"
    COMPLETED = "completed", "Completed"
    SUSPENDED = "suspended", "Suspended"


class Enrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    learner = models.ForeignKey(
        "users.LearnerProfile",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    qualification = models.ForeignKey(
        "qualifications.Qualification",
        on_delete=models.PROTECT,
        related_name="learner_enrollments",
    )

    cohort = models.CharField(max_length=40, help_text='e.g. "2026-Spring"')
    employer = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE,
        db_index=True,
    )

    enrolled_at = models.DateTimeField(default=timezone.now)
    expected_end_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "enrollments"
        indexes = [
            models.Index(fields=["learner", "status"]),
            models.Index(fields=["qualification", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "qualification", "cohort"],
                name="unique_learner_enrollment_cohort",
            ),
        ]
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.learner.learner_id} → {self.qualification.code} ({self.cohort})"


# ─────────────────────────────────────────────────────────────
# Reasonable Adjustment — per learner, per request
# ─────────────────────────────────────────────────────────────

class ReasonableAdjustment(models.Model):
    """
    Created/managed in AdminLearners modal (Section 3) and AdminAdjustments page.
    Linked into ExamSession.reasonable_adjustment_id at session creation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    learner = models.ForeignKey(
        "users.LearnerProfile",
        on_delete=models.CASCADE,
        related_name="reasonable_adjustments",
    )

    notes = models.TextField(help_text="What the learner needs (extra time, reader, etc.)")
    accepted = models.BooleanField(default=False)
    denied = models.BooleanField(default=False)
    denial_reason = models.TextField(blank=True)
    extra_time_minutes = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_adjustments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reasonable_adjustments"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["learner", "accepted"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(accepted=False) | models.Q(denied=False),
                name="reasonable_adjustment_not_accepted_and_denied",
            ),
            # Mirrors the API-level validator: every adjustment must be
            # actioned (Accepted or Denied) — no "pending" state.
            models.CheckConstraint(
                condition=models.Q(accepted=True) | models.Q(denied=True),
                name="reasonable_adjustment_must_be_accepted_or_denied",
            ),
            models.CheckConstraint(
                condition=models.Q(denied=False) | ~models.Q(denial_reason=""),
                name="reasonable_adjustment_denial_has_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(extra_time_minutes__lte=240),
                name="reasonable_adjustment_extra_time_lte_240",
            ),
        ]

    def __str__(self):
        state = "accepted" if self.accepted else "denied" if self.denied else "pending"
        return f"RA[{state}] {self.learner.learner_id} (+{self.extra_time_minutes}m)"

    def clean(self):
        validate_reasonable_adjustment_state(
            accepted=self.accepted,
            denied=self.denied,
            denial_reason=self.denial_reason,
        )
