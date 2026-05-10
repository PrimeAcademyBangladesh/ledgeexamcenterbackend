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
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import filters, generics, mixins, serializers as drf_serializers, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny

from core.mixins import AuditLogMixin, SerializerByActionMixin
from core.permission import IsAdmin, IsAdminOrReadOnlyForStaff
from core.responses import APIResponse
from core.schemas import (
    DEFAULT_ERROR_RESPONSES,
    EmptyEnvelope,
    envelope_action,
    envelope_detail,
    envelope_list,
)

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
#  Common OpenAPI parameters
# ────────────────────────────────────────────────────────────
INCLUDE_INACTIVE_PARAM = OpenApiParameter(
    name="include_inactive",
    type=OpenApiTypes.BOOL,
    location=OpenApiParameter.QUERY,
    required=False,
    description="If `true`, include rows where `is_active=false`. Defaults to false.",
)

# ────────────────────────────────────────────────────────────
#  Tag constants — match drf-spectacular `tags=[...]` everywhere
# ────────────────────────────────────────────────────────────
TAG_QUALIFICATION = "Qualification"
TAG_SECTOR = "Qualification Sector"
TAG_LEVEL = "Qualification Level"
TAG_UNIT = "Qualification Unit"
TAG_ENROLLMENT = "Qualification Enrollment"


# ────────────────────────────────────────────────────────────
#  Sector
# ────────────────────────────────────────────────────────────
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_SECTOR],
        summary="List sectors",
        parameters=[INCLUDE_INACTIVE_PARAM],
        responses={200: envelope_list(SectorSerializer, message_example="Sectors retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_SECTOR],
        summary="Retrieve a sector",
        responses={200: envelope_detail(SectorSerializer, message_example="Sector retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_SECTOR],
        summary="Create a sector",
        request=SectorSerializer,
        responses={201: envelope_detail(SectorSerializer, message_example="Sector created successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=[TAG_SECTOR],
        summary="Replace a sector",
        request=SectorSerializer,
        responses={200: envelope_detail(SectorSerializer, message_example="Sector updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=[TAG_SECTOR],
        summary="Partially update a sector",
        request=SectorSerializer,
        responses={200: envelope_detail(SectorSerializer, message_example="Sector updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=[TAG_SECTOR],
        summary="Delete a sector",
        description="Hard-deletes a sector. Fails with 409 if any qualification still references it.",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
    ),
)
class SectorViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Admin-managed sector list. Powers every "Sector" dropdown in the UI.
    Where:
      - GET    /api/sectors/                → AdminQualifications + AdminExams + AdminQuestionBank + AdminReports dropdowns
      - GET    /api/sectors/{id}/           → Admin Sectors settings page (planned)
      - POST   /api/sectors/                → "Add Sector" admin form
      - PATCH  /api/sectors/{id}/           → Toggle is_active, rename, reorder
      - DELETE /api/sectors/{id}/           → Hard delete (PROTECTED if any Qualification refs it)
    Notes:
      - Default queryset hides inactive sectors. Admin can pass ?include_inactive=true
        to see soft-disabled rows on the management page.
      - List endpoint is ETag-cached for 5 min; mutation invalidates the tag.
    """
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
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_LEVEL],
        summary="List levels",
        responses={200: LevelSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=[TAG_LEVEL],
        summary="Retrieve level",
        responses={200: LevelSerializer},
    ),
    create=extend_schema(
        tags=[TAG_LEVEL],
        summary="Create level",
        request=LevelSerializer,
        responses={201: LevelSerializer},
    ),
    update=extend_schema(
        tags=[TAG_LEVEL],
        summary="Update level",
        request=LevelSerializer,
        responses={200: LevelSerializer},
    ),
    partial_update=extend_schema(
        tags=[TAG_LEVEL],
        summary="Partially update level",
        request=LevelSerializer,
        responses={200: LevelSerializer},
    ),
    destroy=extend_schema(
        tags=[TAG_LEVEL],
        summary="Delete level",
        responses={204: None},
    ),
)
class LevelViewSet(viewsets.ModelViewSet):
    """
    CRUD API for RQF levels.
    """

    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    # permission_classes = [IsAdminOrReadOnlyForStaff]
    permission_classes = [AllowAny]
    pagination_class = None
    ordering = ["name"]


# ────────────────────────────────────────────────────────────
#  Qualification
# ────────────────────────────────────────────────────────────
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="List qualifications",
        parameters=[INCLUDE_INACTIVE_PARAM],
        responses={
            200: envelope_list(QualificationListSerializer, message_example="Qualifications retrieved successfully."),
            **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Retrieve a qualification",
        responses={200: envelope_detail(QualificationDetailSerializer,
                                        message_example="Qualification retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Create a qualification",
        request=QualificationWriteSerializer,
        responses={
            201: envelope_detail(QualificationWriteSerializer, message_example="Qualification created successfully."),
            **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Replace a qualification",
        request=QualificationWriteSerializer,
        responses={
            200: envelope_detail(QualificationWriteSerializer, message_example="Qualification updated successfully."),
            **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Partially update a qualification",
        request=QualificationWriteSerializer,
        responses={
            200: envelope_detail(QualificationWriteSerializer, message_example="Qualification updated successfully."),
            **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Delete a qualification",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
    ),
)
class QualificationViewSet(SerializerByActionMixin, AuditLogMixin, viewsets.ModelViewSet):
    """
    Qualification catalogue endpoint used across admin and learner surfaces.

    Frontend usage:
      - `GET /api/qualifications/` feeds admin dropdowns and tables. It is
        paginated by default, so the UI should read `data.results`.
      - `GET /api/qualifications/{id}/` provides the full admin detail payload
        used to pre-fill edit forms.
      - `POST/PATCH/PUT` accept the write serializer shape and currently return
        the same write-oriented shape with server defaults materialised.
      - Learner-facing screens must use `/api/me/qualifications/` instead of
        this view to avoid exposing admin-only fields.

    Permissions:
      - Read: admin + invigilator. Learners go through /api/me/qualifications/
              (separate view, returns lean payload without resit fields).
      - Write: admin only.
    Performance:
      - List: select_related sector+level, annotate question_count.
      - Detail: prefetch units; bankHealth computed via annotated query, not Python.
    """
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

    @extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Retrieve question-bank health for a qualification",
        responses={
            200: envelope_action(
                {
                    "current": drf_serializers.IntegerField(),
                    "target": drf_serializers.IntegerField(),
                    "min": drf_serializers.IntegerField(),
                    "percent": drf_serializers.FloatField(),
                    "status": drf_serializers.ChoiceField(choices=["healthy", "warning", "critical"]),
                },
                name="QualificationBankHealth",
                message_example="Bank health retrieved successfully.",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    )
    @action(detail=True, methods=["get"], url_path="bank-health")
    def bank_health(self, request, pk=None):
        """
        Lightweight polling endpoint for the question-bank meter in the admin
        question editor.

        The frontend can call this independently from qualification detail to
        refresh the bank status without reloading units, sector, and level
        metadata.
        """
        from django.shortcuts import get_object_or_404
        qual = get_object_or_404(
            Qualification.objects.only("id", "recommended_bank_size", "min_bank_size"),
            pk=pk,
        )
        self.check_object_permissions(request, qual)
        return APIResponse.ok(
            data=selectors.qualification_bank_health(qual),
            message="Bank health retrieved successfully.",
        )

    @extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="List units belonging to a qualification",
        responses={
            200: envelope_detail(
                QualificationUnitSerializer(many=True),
                message_example="Units retrieved successfully.",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    )
    @action(detail=True, methods=["get"])
    def units(self, request, pk=None):
        """
        Return the unit list for a qualification in DB sort order.

        Frontend usage:
          - The question editor can call this to populate a qualification-
            scoped unit picker without first fetching qualification detail.
        """
        # Object-level perms here are class-wide (admin vs staff read), so a
        # bare existence check is enough to enforce the permission contract.
        if not Qualification.objects.filter(pk=pk).exists():
            from django.http import Http404
            raise Http404("Qualification not found.")
        units = QualificationUnit.objects.filter(qualification_id=pk).order_by("sort_order")
        return APIResponse.ok(
            data=QualificationUnitSerializer(units, many=True).data,
            message="Units retrieved successfully.",
        )

    @extend_schema(
        tags=[TAG_QUALIFICATION],
        summary="Qualification dropdown list",
        responses={
            200: envelope_action(
                {
                    "id": drf_serializers.IntegerField(),
                    "title": drf_serializers.CharField(),
                },
                many=True,
                name="QualificationDropdown",
                message_example="Qualification dropdown retrieved successfully.",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    )
    @action(detail=False, methods=["get"], url_path="dropdown")
    def dropdown(self, request):
        """
        Lightweight qualification dropdown endpoint.

        Returns only:
          - id
          - title

        Frontend usage:
          - Select dropdowns
          - React select
          - Autocomplete
        """
        queryset = (
            Qualification.objects
            .filter(is_active=True)
            .only("id", "title")
            .order_by("title")
        )

        data = [
            {
                "id": item.id,
                "title": item.title,
            }
            for item in queryset
        ]

        return APIResponse.ok(
            data=data,
            message="Qualification dropdown retrieved successfully.",
        )


@extend_schema(
    tags=[TAG_QUALIFICATION],
    summary="List qualifications the current learner is enrolled on",
    responses={
        200: envelope_list(QualificationListSerializer, message_example="Your qualifications retrieved successfully."),
        **DEFAULT_ERROR_RESPONSES,
    },
)
class MyQualificationsView(generics.ListAPIView):
    """
    Why: Learners must NOT see resit_fail_margin_percent, min_bank_size, etc.
         (information disclosure → learners could game the resit threshold).
         Separate endpoint with a stripped serializer is safer than runtime
         field hiding.
    Where:
      - GET /api/me/qualifications/  → LearnerDashboard.tsx "Your qualification" card.
    Source of truth:
      - Enrollments are owned by apps.learners.Enrollment (FK to LearnerProfile),
        which is what AdminLearners writes during registration. The parallel
        QualificationEnrollment model is unused by the registration flow, so we
        join through the learners app to find the qualifications.
    """
    queryset = Qualification.objects.none()
    serializer_class = QualificationListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Qualification.objects.none()
        from apps.learners.models import Enrollment, EnrollmentStatus
        qual_ids = (
            Enrollment.objects
            .filter(learner__user=self.request.user, status=EnrollmentStatus.ACTIVE)
            .values_list("qualification_id", flat=True)
        )
        return (
            Qualification.objects
            .filter(id__in=qual_ids, is_active=True)
            .with_relations()
            .with_question_count()
        )


# ────────────────────────────────────────────────────────────
#  QualificationUnit
# ────────────────────────────────────────────────────────────
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_UNIT],
        summary="List qualification units",
        responses={200: envelope_list(QualificationUnitSerializer, message_example="Units retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_UNIT],
        summary="Retrieve a qualification unit",
        responses={200: envelope_detail(QualificationUnitSerializer, message_example="Unit retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_UNIT],
        summary="Create a qualification unit",
        request=QualificationUnitSerializer,
        responses={201: envelope_detail(QualificationUnitSerializer, message_example="Unit created successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=[TAG_UNIT],
        summary="Replace a qualification unit",
        request=QualificationUnitSerializer,
        responses={200: envelope_detail(QualificationUnitSerializer, message_example="Unit updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=[TAG_UNIT],
        summary="Partially update a qualification unit",
        request=QualificationUnitSerializer,
        responses={200: envelope_detail(QualificationUnitSerializer, message_example="Unit updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=[TAG_UNIT],
        summary="Delete a qualification unit",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
    ),
)
class QualificationUnitViewSet(AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Units are admin-managed sub-topics. Used for question tagging and
         per-unit analytics.
    Where:
      - GET   /api/qualifications/{qid}/units/    → AdminQuestionBank tag picker
      - POST  /api/qualifications/{qid}/units/    → "Manage Units" modal
      - PATCH /api/units/{id}/                    → Inline edit
    Routing:
      - Nested under qualifications via drf-nested-routers, OR exposed flat
        with `?qualification={id}` filter. Pick one and stay consistent —
        recommendation: nested for writes, flat for reads.
    """
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
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="List enrolments",
        responses={200: envelope_list(EnrollmentReadSerializer, message_example="Enrolments retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="Retrieve an enrolment",
        responses={200: envelope_detail(EnrollmentReadSerializer, message_example="Enrolment retrieved successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="Create an enrolment",
        request=EnrollmentWriteSerializer,
        responses={201: envelope_detail(EnrollmentReadSerializer, message_example="Enrolment created successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="Replace an enrolment",
        request=EnrollmentWriteSerializer,
        responses={200: envelope_detail(EnrollmentReadSerializer, message_example="Enrolment updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="Partially update an enrolment",
        request=EnrollmentWriteSerializer,
        responses={200: envelope_detail(EnrollmentReadSerializer, message_example="Enrolment updated successfully."),
                   **DEFAULT_ERROR_RESPONSES},
    ),
    destroy=extend_schema(
        tags=[TAG_ENROLLMENT],
        summary="Withdraw an enrolment (soft-delete)",
        description="Sets `status='withdrawn'` and `withdrawn_at=today`. The row is preserved for audit.",
        responses={204: None, **DEFAULT_ERROR_RESPONSES},
    ),
)
class EnrollmentViewSet(SerializerByActionMixin, AuditLogMixin, viewsets.ModelViewSet):
    """
    Why: Admin-only CRUD for learner enrolments. Drives the AdminLearners
         "Add/Edit Learner" form (which currently sets a flat qualificationId
         on the learner — that field will move here).
    Where:
      - GET    /api/enrollments/?learner={id}      → AdminLearners detail drawer
      - POST   /api/enrollments/                   → "Add Learner" form
      - PATCH  /api/enrollments/{id}/              → "Edit" / "Withdraw" actions
      - DELETE /api/enrollments/{id}/              → Soft-delete only (sets status=withdrawn)
    Permissions:
      - Admin: full CRUD.
      - Invigilator: read-only on enrolments for sessions they invigilate.
      - Learner: denied (use /api/me/enrollments/).
    """
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


@extend_schema(
    tags=[TAG_ENROLLMENT],
    summary="List the current learner's enrolments",
    responses={
        200: envelope_list(EnrollmentReadSerializer, message_example="Your enrolments retrieved successfully."),
        **DEFAULT_ERROR_RESPONSES,
    },
)
class MyEnrollmentsView(generics.ListAPIView):
    """
    Why: Learners need to see what they're enrolled on, but must not see
         other learners' rows or admin-only notes.
    Where:
      - GET /api/me/enrollments/  → LearnerDashboard.tsx top card
    Source of truth:
      - Returns rows from apps.learners.Enrollment (the model that
        AdminLearners writes), serialised via the learners app's
        EnrollmentSerializer to match /learner/me/enrollments/.
    """
    queryset = QualificationEnrollment.objects.none()  # for spectacular schema introspection
    serializer_class = EnrollmentReadSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from apps.learners.serializers import EnrollmentSerializer as LearnerEnrollmentSerializer
        return LearnerEnrollmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QualificationEnrollment.objects.none()
        from apps.learners.models import Enrollment
        return (
            Enrollment.objects
            .filter(learner__user=self.request.user)
            .select_related("learner__user", "qualification")
            .order_by("-enrolled_at")
        )


# ────────────────────────────────────────────────────────────
#  Bulk import (CSV)
# ────────────────────────────────────────────────────────────
@extend_schema(
    tags=[TAG_ENROLLMENT],
    summary="Bulk-import enrolments from a CSV file",
    description=(
            "Accepts a multipart/form-data CSV. Required columns: "
            "`learner_id, qualification_id, cohort, enrolled_at`. "
            "Optional: `employer, status, expected_end_date, notes`. "
            "The natural key `(learner_id, qualification_id, cohort)` is upserted."
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
            },
            "required": ["file"],
        }
    },
    responses={
        201: envelope_action(
            {"created": drf_serializers.IntegerField()},
            name="BulkEnrollmentImport",
            message_example="N enrolment(s) imported successfully.",
        ),
        **DEFAULT_ERROR_RESPONSES,
    },
)
class BulkEnrollmentImportView(generics.GenericAPIView):
    """
    Why: AdminLearners.tsx will need a CSV import path (office onboards
         cohorts of 50–200 learners at once). One row per (learner, qual, cohort).
    Where:
      - POST /api/enrollments/bulk-import/   (multipart, file=enrollments.csv)
    Behaviour:
      - Atomic transaction: either ALL rows pass validation or NONE are written.
      - Returns per-row errors for the UI to render in a table.
      - Idempotent: re-uploading the same CSV is a no-op (unique constraint).
    """
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
