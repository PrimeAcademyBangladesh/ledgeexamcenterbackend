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


# ────────────────────────────────────────────────────────────
#  Sector / Level — referential integrity guards
# ────────────────────────────────────────────────────────────
def assert_sector_deletable(sector) -> None:
    if sector.qualifications.exists():
        raise ConflictError(
            "Cannot deactivate sector while qualifications reference it. "
            "Deactivate or reassign those qualifications first."
        )


def assert_level_deletable(level) -> None:
    if level.qualifications.exists():
        raise ConflictError(
            "Cannot deactivate level while qualifications reference it. "
            "Deactivate or reassign those qualifications first."
        )
