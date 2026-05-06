"""
apps/qualifications/views.py
Lead Edge Ltd EPAO Exam Platform

Views are thin: they wire HTTP → selector (read) or service (write).
* Selectors return querysets — DRF handles filter/order/pagination on top.
* Services own writes — call them, never duplicate their logic here.
* Responses are auto-wrapped by core.renderers.EnvelopeJSONRenderer.
"""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated

from core.mixins import AuditLogMixin, SerializerByActionMixin
from core.permission import IsAdmin, IsAdminOrReadOnlyForStaff
from core.responses import APIResponse

from . import selectors, services
from .models import (
    Level,
    Qualification,
    QualificationEnrollment,
    QualificationUnit,
    Sector,
)
from .serializers import (
    EnrollmentReadSerializer,
    EnrollmentWriteSerializer,
    LevelSerializer,
    QualificationDetailSerializer,
    QualificationListSerializer,
    QualificationUnitSerializer,
    QualificationWriteSerializer,
    SectorSerializer,
)


def _include_inactive(request) -> bool:
    return request.query_params.get("include_inactive") == "true"


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
class SectorViewSet(AuditLogMixin, viewsets.ModelViewSet):
    queryset = Sector.objects.all()  # for router introspection
    serializer_class = SectorSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "code"]
    ordering_fields = ["sort_order", "name"]
    ordering = ["sort_order", "name"]

    def get_queryset(self):
        return selectors.sector_list_qs(include_inactive=_include_inactive(self.request))

    def perform_destroy(self, instance):
        services.assert_sector_deletable(instance)
        super().perform_destroy(instance)


# ────────────────────────────────────────────────────────────
#  Level
# ────────────────────────────────────────────────────────────
class LevelViewSet(AuditLogMixin, viewsets.ModelViewSet):
    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [filters.OrderingFilter]
    ordering = ["numeric_value"]

    def get_queryset(self):
        return selectors.level_list_qs(include_inactive=_include_inactive(self.request))

    def perform_destroy(self, instance):
        services.assert_level_deletable(instance)
        super().perform_destroy(instance)


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
class QualificationViewSet(SerializerByActionMixin, AuditLogMixin, viewsets.ModelViewSet):
    queryset = Qualification.objects.all()
    serializer_class = QualificationDetailSerializer
    serializer_action_classes = {
        "list": QualificationListSerializer,
        "create": QualificationWriteSerializer,
        "update": QualificationWriteSerializer,
        "partial_update": QualificationWriteSerializer,
    }
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["sector", "level", "is_active"]
    search_fields = ["title", "code"]
    ordering_fields = ["title", "code", "created_at"]
    ordering = ["title"]

    def get_queryset(self):
        action = self.action
        if action == "list":
            return selectors.qualification_list_qs(
                include_inactive=_include_inactive(self.request)
            )
        if action in ("retrieve", "bank_health", "units"):
            return selectors.qualification_detail_qs(include_inactive=True)
        # create/update/destroy — relations are enough.
        return Qualification.objects.with_relations()

    @action(detail=True, methods=["get"], url_path="bank-health")
    def bank_health(self, request, pk=None):
        qual = self.get_object()
        return APIResponse.ok(
            data=selectors.qualification_bank_health(qual),
            message="Bank health retrieved successfully.",
        )

    @action(detail=True, methods=["get"])
    def units(self, request, pk=None):
        qual = self.get_object()
        units = sorted(qual.units.all(), key=lambda u: u.sort_order)
        return APIResponse.ok(
            data=QualificationUnitSerializer(units, many=True).data,
            message="Units retrieved successfully.",
        )


class MyQualificationsView(generics.ListAPIView):
    """Learner-safe — strips resit/bank fields by reusing the list serializer."""
    serializer_class = QualificationListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return selectors.qualification_for_learner_qs(self.request.user)


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
class QualificationUnitViewSet(AuditLogMixin, viewsets.ModelViewSet):
    queryset = QualificationUnit.objects.all()
    serializer_class = QualificationUnitSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["qualification"]
    ordering = ["qualification", "sort_order"]

    def get_queryset(self):
        return selectors.unit_list_qs(
            qualification_id=self.request.query_params.get("qualification")
        )


# ────────────────────────────────────────────────────────────
#  Enrollment
# ────────────────────────────────────────────────────────────
class EnrollmentViewSet(SerializerByActionMixin, AuditLogMixin, viewsets.ModelViewSet):
    queryset = QualificationEnrollment.objects.all()
    serializer_class = EnrollmentReadSerializer
    serializer_action_classes = {
        "create": EnrollmentWriteSerializer,
        "update": EnrollmentWriteSerializer,
        "partial_update": EnrollmentWriteSerializer,
    }
    permission_classes = [IsAdminOrReadOnlyForStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["learner", "qualification", "status", "cohort", "employer"]
    search_fields = [
        "learner__email", "learner__first_name", "learner__last_name",
        "qualification__title", "qualification__code",
    ]

    def get_queryset(self):
        return selectors.enrollment_list_qs(self.request.user)

    def perform_destroy(self, instance):
        services.withdraw_enrollment(instance)
        self._audit("withdraw", instance)


class MyEnrollmentsView(generics.ListAPIView):
    serializer_class = EnrollmentReadSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return selectors.enrollment_for_learner_qs(self.request.user)


# ────────────────────────────────────────────────────────────
#  Bulk import (CSV)
# ────────────────────────────────────────────────────────────
class BulkEnrollmentImportView(generics.GenericAPIView):
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser]
    serializer_class = EnrollmentReadSerializer  # for browsable API only

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return APIResponse.fail(
                message="A CSV file is required.",
                errors={"file": ["This field is required."]},
                status=400,
            )

        from .services_imports import parse_enrollment_csv

        rows, errors = parse_enrollment_csv(file)
        if errors:
            return APIResponse.fail(
                message="The uploaded CSV contains errors.",
                errors={"rows": errors},
                status=400,
            )

        created = services.bulk_upsert_enrollments(rows)
        return APIResponse.ok(
            data={"created": len(created)},
            message=f"{len(created)} enrolment(s) imported successfully.",
            status=201,
        )
