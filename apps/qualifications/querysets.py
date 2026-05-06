"""
apps/qualifications/querysets.py
Chainable QuerySets + Managers. Keeps query shape declarative and
testable without bloating views or serializers.
"""
from __future__ import annotations

from django.db import models
from django.db.models import Count, Q


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
class SectorQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_qualification_count(self):
        return self.annotate(qualification_count=Count("qualifications"))


# ────────────────────────────────────────────────────────────
#  Level
# ────────────────────────────────────────────────────────────
class LevelQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
class QualificationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_relations(self):
        return self.select_related("sector", "level")

    def with_question_count(self):
        # Defensive: only annotate if a reverse `questions` relation exists.
        if not hasattr(self.model, "questions"):
            return self
        return self.annotate(
            question_count=Count("questions", filter=Q(questions__is_active=True))
        )

    def for_list(self):
        return self.with_relations().with_question_count()

    def for_detail(self):
        return self.with_relations().prefetch_related("units")

    def enrolled_by(self, user):
        return self.filter(
            enrollments__learner=user,
            enrollments__status="active",
        ).distinct()


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnitQuerySet(models.QuerySet):
    def with_relations(self):
        return self.select_related("qualification")

    def by_qualification(self, qualification_id):
        return self.filter(qualification_id=qualification_id)


# ────────────────────────────────────────────────────────────
#  QualificationEnrollment
# ────────────────────────────────────────────────────────────
class QualificationEnrollmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status="active")

    def with_relations(self):
        return self.select_related("learner", "qualification")

    def for_learner(self, user):
        return self.filter(learner=user)

    def for_invigilator(self, user):
        # Assumes a related `learner.sessions__invigilator` path; tolerate absence.
        return self.filter(learner__sessions__invigilator=user).distinct()
