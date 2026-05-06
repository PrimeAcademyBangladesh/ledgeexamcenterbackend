"""
django-filter integration — powers the admin search/filter row on
`/admin/invigilators` (search by name, email, provider code).
"""
import django_filters
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.users.models import Role
from .models import ProviderCentre

User = get_user_model()


class InvigilatorFilter(django_filters.FilterSet):
    search        = django_filters.CharFilter(method="filter_search")
    isActive      = django_filters.BooleanFilter(field_name="is_active")
    providerCode  = django_filters.CharFilter(method="filter_provider_code")

    class Meta:
        model = User
        fields = ["isActive", "providerCode"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(first_name__icontains=value)
            | Q(last_name__icontains=value)
            | Q(email__icontains=value)
            | Q(staff_profile__provider_code__icontains=value)
        )

    def filter_provider_code(self, queryset, name, value):
        return queryset.filter(staff_profile__provider_code__iexact=value.strip())


class ProviderCentreFilter(django_filters.FilterSet):
    search   = django_filters.CharFilter(method="filter_search")
    isActive = django_filters.BooleanFilter(field_name="is_active")

    class Meta:
        model = ProviderCentre
        fields = ["isActive"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(code__icontains=value) | Q(city__icontains=value)
        )
