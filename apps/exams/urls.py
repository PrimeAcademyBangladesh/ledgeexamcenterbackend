"""
URL routing for the Exams app.
Mounted under "/exams/" by the project urls.py — paths here are flat.

Resulting endpoints (all prefixed with /exams/):
    /                       — ExamConfig CRUD
    /<id>/                  — ExamConfig detail
    /sessions/              — ExamSession CRUD (+ pin/, draft/, verify-id/, unlock/, complete/)
    /results/               — ExamResult CRUD
    /retakes/               — RetakeRequest CRUD
    /mock/                  — MockExamList
    /mock/<id>/start/       — MockExamStart
    /validate-pin/          — ValidatePin
    /<sid>/submit/          — SubmitExam
    /violations/            — ReportViolation
    /retakes/request/       — RequestRetake
    /retakes/<id>/approve/  — ApproveRetake
    /retakes/<id>/deny/     — DenyRetake
    /retakes/resit/         — CreateResitSession
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ApproveRetakeView,
    CreateResitSessionView,
    DenyRetakeView,
    ExamConfigViewSet,
    ExamDropdownViewSet,
    ExamResultViewSet,
    ExamSessionViewSet,
    MockExamListView,
    MockExamStartView,
    ReportViolationView,
    RequestRetakeView,
    RetakeRequestViewSet,
    SubmitExamView,
    ValidatePinView,
)

router = DefaultRouter()
router.register(r"sessions", ExamSessionViewSet, basename="exam-session")
router.register(r"results", ExamResultViewSet, basename="result")
router.register(r"retakes", RetakeRequestViewSet, basename="retake")
# Register ExamConfig last with empty prefix so /mock/, /sessions/, etc. resolve first.
router.register(r"", ExamConfigViewSet, basename="exam")

urlpatterns = [
    path("dropdown/", ExamDropdownViewSet.as_view(), name="exam-dropdown"),
    path("mock/", MockExamListView.as_view(), name="exam-mock-list"),
    path("mock/<uuid:exam_id>/start/", MockExamStartView.as_view(), name="exam-mock-start"),

    # Learner runtime
    path("validate-pin/", ValidatePinView.as_view(), name="exam-validate-pin"),
    path("<uuid:session_id>/submit/", SubmitExamView.as_view(), name="exam-submit"),

    # Integrity (kept under /exams/ as the original layout intended)
    path("violations/", ReportViolationView.as_view(), name="report-violation"),

    # Retake / Resit specific actions
    path("retakes/request/", RequestRetakeView.as_view(), name="retake-request"),
    path("retakes/<uuid:retake_id>/approve/", ApproveRetakeView.as_view(), name="retake-approve"),
    path("retakes/<uuid:retake_id>/deny/", DenyRetakeView.as_view(), name="retake-deny"),
    path("retakes/resit/", CreateResitSessionView.as_view(), name="retake-resit"),

    path("", include(router.urls)),
]
