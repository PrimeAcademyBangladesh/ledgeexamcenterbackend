"""
apps/learners/filters.py
Powers AdminLearners search box + qualification filter.
"""
import django_filters
from django.db.models import Q, Value
from django.db.models.functions import Concat

from apps.users.models import LearnerProfile


class LearnerFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search")
    qualificationId = django_filters.UUIDFilter(field_name="enrollments__qualification_id", distinct=True)
    isActive = django_filters.BooleanFilter(field_name="user__is_active")
    cohort = django_filters.CharFilter(field_name="enrollments__cohort", distinct=True)

    class Meta:
        model = LearnerProfile
        fields = ["search", "qualificationId", "isActive", "cohort"]

    def filter_search(self, qs, name, value):
        if not value:
            return qs
        # Match first/last name individually as well as "First Last" combined,
        # so searching by a learner's full name returns results.
        return qs.annotate(
            full_name=Concat("user__first_name", Value(" "), "user__last_name")
        ).filter(
            Q(user__first_name__icontains=value)
            | Q(user__last_name__icontains=value)
            | Q(full_name__icontains=value)
            | Q(user__email__icontains=value)
            | Q(uln__icontains=value)
            | Q(learner_id__icontains=value)
        )
