"""
apps/qualifications/services.py
Write-side business logic. Views call services — services own DB writes,
validation, and cross-model invariants.

Rules:
    * Always wrap multi-row writes in transaction.atomic.
    * Raise rest_framework.exceptions.ValidationError (or DomainError) for
      caller-visible failures so the global exception handler emits the envelope.
    * No DRF Request objects in here — pass primitives or model instances.
"""
from __future__ import annotations

from typing import Iterable

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.exceptions import ConflictError

from .models import QualificationEnrollment


# ────────────────────────────────────────────────────────────
#  Enrollment
# ────────────────────────────────────────────────────────────
@transaction.atomic
def withdraw_enrollment(enrollment: QualificationEnrollment, *, reason: str = "") -> QualificationEnrollment:
    """Soft-delete an enrolment. Idempotent on already-withdrawn rows."""
    if enrollment.status == "withdrawn":
        return enrollment
    enrollment.status = "withdrawn"
    enrollment.withdrawn_at = timezone.now().date()
    if reason:
        enrollment.withdrawal_reason = reason
    enrollment.save(update_fields=["status", "withdrawn_at", "withdrawal_reason", "updated_at"])
    return enrollment


@transaction.atomic
def bulk_upsert_enrollments(rows: Iterable[dict]) -> list[QualificationEnrollment]:
    """
    Idempotent bulk import: (learner_id, qualification_id, cohort) is the
    natural key. Existing rows are updated; new ones inserted.

    `rows` items must contain at minimum:
        learner_id, qualification_id, cohort
    Optional:
        employer, status, enrolled_at, expected_end_date, notes
    """
    rows = list(rows)
    if not rows:
        return []

    # Deduplicate on natural key — last write wins.
    deduped: dict[tuple, dict] = {}
    for r in rows:
        try:
            key = (r["learner_id"], r["qualification_id"], r["cohort"])
        except KeyError as e:
            raise ValidationError(f"Missing key in import row: {e.args[0]}")
        deduped[key] = r

    saved: list[QualificationEnrollment] = []
    for key, payload in deduped.items():
        learner_id, qualification_id, cohort = key
        obj, _ = QualificationEnrollment.objects.update_or_create(
            learner_id=learner_id,
            qualification_id=qualification_id,
            cohort=cohort,
            defaults={k: v for k, v in payload.items() if k not in {"learner_id", "qualification_id", "cohort"}},
        )
        saved.append(obj)
    return saved


# ────────────────────────────────────────────────────────────
#  Sector / Level — referential integrity guards
# ────────────────────────────────────────────────────────────
def assert_sector_deletable(sector) -> None:
    if sector.qualifications.exists():
        raise ConflictError(
            "Cannot delete sector while qualifications reference it. "
            "Set is_active=false instead."
        )


def assert_level_deletable(level) -> None:
    if level.qualifications.exists():
        raise ConflictError(
            "Cannot delete level while qualifications reference it. "
            "Set is_active=false instead."
        )
