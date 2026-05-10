"""
apps/qualifications/querysets.py

Reusable chainable QuerySets for the qualifications domain.

Design goals:
    - Centralise query optimisation.
    - Keep views/selectors lightweight.
    - Prevent N+1 queries.
    - Make query intent reusable and testable.
    - Encapsulate business filtering rules close to the ORM layer.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Count, Prefetch, Q


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
class SectorQuerySet(models.QuerySet):
    """
    Query helpers for qualification sectors.
    """

    def active(self):
        """
        Return active sectors only.
        """
        return self.filter(is_active=True)

    def with_qualification_count(self):
        """
        Annotate total qualification count per sector.
        """
        return self.annotate(
            qualification_count=Count(
                "qualifications",
                distinct=True,
            )
        )


# ────────────────────────────────────────────────────────────
#  Level
# ────────────────────────────────────────────────────────────
class LevelQuerySet(models.QuerySet):
    """
    Query helpers for qualification levels.
    """

    def active(self):
        """
        Placeholder for future parity with other models.
        """
        return self


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
class QualificationQuerySet(models.QuerySet):
    """
    Query helpers for qualifications.

    Provides optimised query shapes for:
        - list endpoints
        - detail endpoints
        - learner enrolments
        - serializer relation loading
        - aggregated counts
    """

    def active(self):
        """
        Return active qualifications only.
        """
        return self.filter(is_active=True)

    def with_relations(self):
        """
        Eager-load commonly accessed FK relations.
        """
        return self.select_related(
            "sector",
            "level",
        )

    def with_question_count(self):
        """
        Annotate active question totals.

        Uses distinct=True to avoid inflated counts caused by joins.
        """
        return self.annotate(
            question_count=Count(
                "questions",
                filter=Q(questions__is_active=True),
                distinct=True,
            )
        )

    def for_list(self):
        """
        Optimised queryset for paginated list/table APIs.

        Includes:
            - sector + level joins
            - question count annotation
            - stable ordering
        """
        return (
            self.with_relations()
            .with_question_count()
            .order_by("title")
        )

    def for_detail(self):
        """
        Optimised queryset for detail/retrieve APIs.

        Includes:
            - sector + level joins
            - question count annotation
            - unit prefetching
        """
        return (
            self.with_relations()
            .with_question_count()
            .prefetch_related(
                Prefetch("units")
            )
        )

    def enrolled_by(self, user):
        """
        Return qualifications actively enrolled by learner.
        """
        return (
            self.filter(
                enrollments__learner=user,
                enrollments__status="active",
            )
            .distinct()
        )


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnitQuerySet(models.QuerySet):
    """
    Query helpers for qualification units.
    """

    def with_relations(self):
        """
        Eager-load qualification relation.
        """
        return self.select_related("qualification")

    def by_qualification(self, qualification_id):
        """
        Filter units by qualification.
        """
        return self.filter(
            qualification_id=qualification_id
        )


# ────────────────────────────────────────────────────────────
#  QualificationEnrollment
# ────────────────────────────────────────────────────────────
class QualificationEnrollmentQuerySet(models.QuerySet):
    """
    Query helpers for qualification enrolments.
    """

    def active(self):
        """
        Return active enrolments only.
        """
        return self.filter(status="active")

    def with_relations(self):
        """
        Eager-load learner + qualification relations.
        """
        return self.select_related(
            "learner",
            "qualification",
        )

    def for_learner(self, user):
        """
        Return enrolments for learner.
        """
        return self.filter(
            learner=user
        )

    def for_invigilator(self, user):
        """
        Return enrolments supervised by invigilator.

        Assumes learner.sessions.invigilator relation exists.
        """
        return (
            self.filter(
                learner__sessions__invigilator=user
            )
            .distinct()
        )