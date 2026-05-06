"""
apps/learners/filters.py
Powers AdminLearners search box + qualification filter.
"""
import django_filters
from django.db.models import Q

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
        return qs.filter(
            Q(user__first_name__icontains=value)
            | Q(user__last_name__icontains=value)
            | Q(user__email__icontains=value)
            | Q(uln__icontains=value)
            | Q(learner_id__icontains=value)
        )
