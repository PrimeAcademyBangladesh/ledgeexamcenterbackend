"""
apps/qualifications/selectors.py
Read-side composition. Views/serializers call selectors instead of
hand-rolling .select_related/.prefetch_related/.annotate chains.

Selectors return querysets (lazy) so they compose with filtering &
pagination — never .all()/.first() unless explicitly named so.
"""
from __future__ import annotations

from django.db.models import Count, Q

from .models import (
    Level,
    Qualification,
    QualificationEnrollment,
    QualificationUnit,
    Sector,
)


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
def sector_list_qs(*, include_inactive: bool = False):
    qs = Sector.objects.with_qualification_count()
    if not include_inactive:
        qs = qs.active()
    return qs


# ────────────────────────────────────────────────────────────
#  Level
# ────────────────────────────────────────────────────────────
def level_list_qs(*, include_inactive: bool = False):
    qs = Level.objects.all()
    if not include_inactive:
        qs = qs.active()
    return qs


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
def qualification_list_qs(*, include_inactive: bool = False):
    qs = Qualification.objects.for_list()
    if not include_inactive:
        qs = qs.active()
    return qs


def qualification_detail_qs(*, include_inactive: bool = False):
    qs = Qualification.objects.for_detail()
    if not include_inactive:
        qs = qs.active()
    return qs


def qualification_for_learner_qs(user):
    return (
        Qualification.objects
        .enrolled_by(user)
        .active()
        .with_relations()
        .with_question_count()
    )


def qualification_bank_health(qualification: Qualification) -> dict:
    """
    Single computed dict reused by serializer + @action endpoint.
    Issues exactly one COUNT query.
    """
    if hasattr(qualification, "questions"):
        total = qualification.questions.filter(is_active=True).count()
    else:
        total = 0
    target = qualification.recommended_bank_size or 1
    return {
        "current": total,
        "target": qualification.recommended_bank_size,
        "min": qualification.min_bank_size,
        "percent": round(min(100.0, (total / target) * 100), 1),
        "status": (
            "healthy" if total >= qualification.recommended_bank_size
            else "warning" if total >= qualification.min_bank_size
            else "critical"
        ),
    }


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
def unit_list_qs(*, qualification_id=None):
    qs = QualificationUnit.objects.with_relations()
    if qualification_id is not None:
        qs = qs.by_qualification(qualification_id)
    return qs


# ────────────────────────────────────────────────────────────
#  Enrollment
# ────────────────────────────────────────────────────────────
def enrollment_list_qs(user):
    qs = QualificationEnrollment.objects.with_relations()
    role = getattr(user, "role", None)
    if role == "invigilator":
        return qs.for_invigilator(user)
    if role == "learner":
        return qs.for_learner(user)
    return qs


def enrollment_for_learner_qs(user):
    return (
        QualificationEnrollment.objects
        .for_learner(user)
        .with_relations()
        .order_by("-enrolled_at")
    )
