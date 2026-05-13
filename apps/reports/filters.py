import django_filters as df
from django.db.models import Q, Value
from django.db.models.functions import Concat

from apps.exams.models import ExamResult


class ReportFilter(df.FilterSet):
    qualification_id = df.UUIDFilter(field_name="qualification_id")
    exam_title = df.CharFilter(field_name="exam_config__title", lookup_expr="iexact")
    grade = df.CharFilter(field_name="grade")
    passed = df.BooleanFilter(field_name="passed")
    date_from = df.DateFilter(field_name="exam_date", lookup_expr="gte")
    date_to = df.DateFilter(field_name="exam_date", lookup_expr="lte")
    learner_id = df.UUIDFilter(field_name="learner_id")
    search = df.CharFilter(method="filter_search")

    class Meta:
        model = ExamResult
        fields = ()

    def filter_search(self, qs, name, value):
        return qs.annotate(
            full_name=Concat("learner__first_name", Value(" "), "learner__last_name")
        ).filter(
            Q(full_name__icontains=value)
            | Q(learner__learner_profile__uln__icontains=value)
            | Q(exam_config__title__icontains=value)
        )
