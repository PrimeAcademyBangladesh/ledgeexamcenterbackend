import csv
import io
from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.views import APIView

from apps.exams.models import ExamResult, ExamSession, IntegrityViolation, RetakeRequest
from core.permission import IsAdmin
from core.responses import APIResponse
from core.schemas import DEFAULT_ERROR_RESPONSES, envelope_detail

from .filters import ReportFilter
from .marksheet import render_marksheet
from .serializers import (
    DashboardAlertsSerializer,
    ReportDetailSerializer,
    ReportRowSerializer,
)
from .stats import compute_stats


REPORT_QUERY_PARAMS = [
    OpenApiParameter("qualification_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
    OpenApiParameter("exam_title", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter("date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY),
    OpenApiParameter("date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY),
    OpenApiParameter("learner_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
    OpenApiParameter("grade", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter("passed", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
    OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
]

REPORT_STATS_SCHEMA = inline_serializer(
    name="ReportStats",
    fields={
        "totalAttempts": serializers.IntegerField(),
        "passRate": serializers.FloatField(),
        "averageScore": serializers.FloatField(),
        "distinctionCount": serializers.IntegerField(),
        "gradeDistribution": serializers.JSONField(),
        "scoreDistribution": serializers.JSONField(),
    },
)

REPORT_LIST_SCHEMA = inline_serializer(
    name="ReportListEnvelope",
    fields={
        "success": serializers.BooleanField(default=True),
        "message": serializers.CharField(),
        "data": inline_serializer(
            name="ReportListData",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True, required=False),
                "previous": serializers.URLField(allow_null=True, required=False),
                "rows": ReportRowSerializer(many=True),
                "stats": REPORT_STATS_SCHEMA,
            },
        ),
    },
)


@extend_schema_view(
    list=extend_schema(
        tags=["Reports"],
        summary="List filtered report rows",
        parameters=REPORT_QUERY_PARAMS,
        responses={200: REPORT_LIST_SCHEMA, **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=["Reports"],
        summary="Retrieve a single result (powers Exam Summary modal)",
        responses={200: envelope_detail(ReportDetailSerializer), **DEFAULT_ERROR_RESPONSES},
    ),
)
class ReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReportFilter
    queryset = ExamResult.objects.select_related(
        "learner",
        "learner__learner_profile",
        "exam_config",
        "qualification",
        "session",
    ).order_by("-submitted_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ReportDetailSerializer
        return ReportRowSerializer

    def retrieve(self, request, *args, **kwargs):
        result = self.get_object()
        return APIResponse.ok(
            data=ReportDetailSerializer(result).data,
            message="Result retrieved successfully.",
        )

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        rows = self.get_serializer(page or qs, many=True).data

        if page is not None:
            return APIResponse.ok(
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "rows": rows,
                    "stats": compute_stats(qs),
                },
                message="Reports retrieved successfully.",
            )

        return APIResponse.ok(
            data={"rows": rows, "stats": compute_stats(qs)},
            message="Reports retrieved successfully.",
        )

def _get_marksheet_result(pk):
    return get_object_or_404(
        ExamResult.objects.select_related(
            "learner", "learner__learner_profile",
            "exam_config", "qualification", "session",
        ),
        pk=pk,
    )


def _marksheet_filename(result) -> str:
    learner = result.learner
    slug = f"{learner.first_name}-{learner.last_name}".lower().replace(" ", "-")
    return f"marksheet-{slug}-{result.exam_date.isoformat()}.pdf"


class MarksheetView(APIView):
    """
    GET /reports/{id}/marksheet/  →  application/pdf (attachment)

    Triggered by the "Marksheet" action on each result row. The PDF mirrors
    the brand: teal header, gold accent rule, score + grade tile, signed-off
    footer. Logo is loaded from static/marksheet/logo.png (drop your logo
    there — the renderer falls back to text if it's missing).
    """
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Reports"],
        summary="Download a learner's exam result as a PDF marksheet",
        responses={
            200: {
                "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
                "description": "Marksheet PDF",
            },
            **DEFAULT_ERROR_RESPONSES,
        },
    )
    def get(self, request, pk):
        result = _get_marksheet_result(pk)
        pdf_bytes = render_marksheet(result)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{_marksheet_filename(result)}"'
        return response


class ReportExportView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Reports"],
        summary="Export filtered reports",
        parameters=REPORT_QUERY_PARAMS + [
            OpenApiParameter(
                "format",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="csv or xlsx",
            )
        ],
        responses={200: None, **DEFAULT_ERROR_RESPONSES},
    )
    def get(self, request):
        qs = ReportFilter(request.query_params, queryset=ExamResult.objects.select_related(
            "learner",
            "learner__learner_profile",
            "exam_config",
            "qualification",
            "session",
        ).order_by("-submitted_at")).qs
        fmt = request.query_params.get("format", "csv").lower()
        rows = ReportRowSerializer(qs, many=True).data

        if fmt == "xlsx":
            try:
                return _xlsx_response(rows)
            except RuntimeError as exc:
                return APIResponse.fail(message=str(exc), status=400)
        return _csv_response(rows)


@extend_schema(
    tags=["Reports"],
    summary="Admin dashboard alert cards",
    responses={200: envelope_detail(DashboardAlertsSerializer), **DEFAULT_ERROR_RESPONSES},
)
class DashboardAlertsView(APIView):
    """
    Compact admin dashboard counters for the first landing screen.

    The backend returns count + routing metadata. Frontend should map
    `target.pageKey` to the exact page route it uses today.
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        cards = [
            {
                "key": "today_exam_schedule",
                "title": "Today's exams",
                "count": ExamSession.objects.exclude(status="cancelled").filter(
                    scheduled_date=today,
                ).count(),
                "level": "info",
                "target": {
                    "pageKey": "exam-sessions",
                    "apiPath": "/api/exams/sessions/",
                    "query": {"scheduled_date": today.isoformat()},
                },
            },
            {
                "key": "upcoming_exam_schedule",
                "title": "Upcoming scheduled exams",
                "count": ExamSession.objects.filter(
                    status="scheduled",
                    scheduled_date__gte=tomorrow,
                ).count(),
                "level": "info",
                "target": {
                    "pageKey": "exam-sessions",
                    "apiPath": "/api/exams/sessions/",
                    "query": {"status": "scheduled", "date_from": tomorrow.isoformat()},
                },
            },
            {
                "key": "new_retake_requests",
                "title": "Pending retake requests",
                "count": RetakeRequest.objects.filter(status="pending").count(),
                "level": "warning",
                "target": {
                    "pageKey": "retake-requests",
                    "apiPath": "/api/exams/retakes/",
                    "query": {"status": "pending"},
                },
            },
            {
                "key": "today_finished_exams",
                "title": "Today's finished exams",
                "count": ExamResult.objects.filter(exam_date=today).count(),
                "level": "success",
                "target": {
                    "pageKey": "reports",
                    "apiPath": "/api/reports/",
                    "query": {"date_from": today.isoformat(), "date_to": today.isoformat()},
                },
            },
            {
                "key": "today_integrity_events",
                "title": "Today's integrity events",
                "count": IntegrityViolation.objects.filter(occurred_at__date=today).count(),
                "level": "danger",
                "target": {
                    "pageKey": "integrity-events",
                    "apiPath": "/api/exams/violations/",
                    "query": {"date_from": today.isoformat(), "date_to": today.isoformat()},
                },
            },
        ]

        return APIResponse.ok(
            data={
                "today": today,
                "generatedAt": timezone.now(),
                "cards": cards,
            },
            message="Dashboard alerts retrieved successfully.",
        )


HEADERS = [
    "Learner Name",
    "ULN",
    "Programme",
    "Exam",
    "Date",
    "Score %",
    "Correct",
    "Total",
    "Grade",
    "Status",
    "Violations",
]


def _row_tuple(row):
    return [
        row["learnerName"],
        row["uln"],
        row["qualificationName"],
        row["examTitle"],
        row["examDate"],
        row["scorePercent"],
        row["correctCount"],
        row["totalQuestions"],
        row["grade"].replace("_", " "),
        "Passed" if row["passed"] else "Did Not Pass",
        row["violationCount"],
    ]


def _csv_response(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow(_row_tuple(row))
    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="lead-edge-results.csv"'
    return response


def _xlsx_response(rows):
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("XLSX export requires openpyxl to be installed.") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(_row_tuple(row))
    buf = io.BytesIO()
    workbook.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="lead-edge-results.xlsx"'
    return response
