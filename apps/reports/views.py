import csv
import io

from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.views import APIView

from apps.exams.models import ExamResult
from core.permission import IsAdmin
from core.responses import APIResponse
from core.schemas import DEFAULT_ERROR_RESPONSES

from .filters import ReportFilter
from .serializers import ReportRowSerializer
from .stats import compute_stats


REPORT_QUERY_PARAMS = [
    OpenApiParameter("qualification_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
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
)
class ReportViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdmin]
    serializer_class = ReportRowSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReportFilter
    queryset = ExamResult.objects.select_related(
        "learner",
        "learner__learner_profile",
        "exam_config",
        "qualification",
        "session",
    ).order_by("-submitted_at")

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
