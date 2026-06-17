"""
Views — DRF.

Endpoint summary (all paths assume the urls.py in this folder):

  GET    /api/exams/                          list ExamConfigs (admin/inv)
  POST   /api/exams/                          create ExamConfig (admin)
  GET    /api/exams/{id}/                     retrieve
  PUT    /api/exams/{id}/                     update
  GET    /api/exams/mock/                     learner-visible published mock exams
  GET    /api/exams/mock/{exam_id}/start/     start a mock without PIN

  GET    /api/exams/sessions/                 list (?learner_id=, ?invigilator_id=)
  POST   /api/exams/sessions/                 create scheduled session (admin)
  PATCH  /api/exams/sessions/{id}/pin/        override PIN (invigilator/admin)
  PATCH  /api/exams/sessions/{id}/draft/      autosave (learner)
  PATCH  /api/exams/sessions/{id}/verify-id/  ID verified flag (invigilator)
  POST   /api/exams/sessions/{id}/unlock/     unlock test (invigilator)
  POST   /api/exams/sessions/{id}/complete/   confirm completion (invigilator)

  POST   /api/exams/validate-pin/             learner — open exam
  POST   /api/exams/{session_id}/submit/      learner — submit + score

  POST   /api/violations/                     learner — record incident

  GET    /api/results/                        list (?learner_id=)
  GET    /api/results/{id}/                   retrieve

  POST   /api/retakes/request/                learner request
  GET    /api/retakes/                        list (?status=, ?learner_id=)
  PUT    /api/retakes/{id}/approve/           admin
  PUT    /api/retakes/{id}/deny/              admin
  POST   /api/retakes/resit/                  invigilator — create resit session
"""
import csv
import io
from datetime import datetime, timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView

from apps.questions.models import Question
from apps.learners.models import Enrollment, EnrollmentStatus, ReasonableAdjustment
from apps.users.models import User
from core.schemas import DEFAULT_ERROR_RESPONSES, envelope_action, envelope_detail, envelope_list
from .models import (
    ExamConfig, ExamSession, ExamResult,
    IntegrityViolation, RetakeRequest,
)
from core.permission import (
    IsAdmin, IsLearner, IsInvigilatorOrAdmin,
    IsAdminOrReadOnlyForStaff, IsSessionLearnerOwner,
)
from core.responses import APIResponse
from core.email import send_email
from .serializers import (
    ExamConfigSerializer,
    ExamConfigDropdownSerializer,
    ExamSessionSerializer, CreateExamSessionSerializer, UpdateSessionPinSerializer,
    ValidatePinRequestSerializer, ValidatePinResponseSerializer,
    SaveExamDraftSerializer, ExamDraftSerializer,
    SubmitExamSerializer, ExamResultSerializer,
    ReportViolationSerializer, IntegrityViolationSerializer,
    ExamQuestionSerializer,
    RetakeRequestSerializer, CreateRetakeRequestSerializer,
    CreateResitSessionSerializer, DenyRetakeSerializer,
    RescheduleExamSessionSerializer,
)
from .services import (
    _generate_pin, _compute_pin_window,
    create_scheduled_session, select_questions_for_learner,
    score_submission, is_resit_eligible,
)
from rest_framework.generics import ListAPIView


TAG_EXAM_CONFIG = "Exam Config"
TAG_EXAM_SESSION = "Exam Session"
TAG_EXAM_RUNTIME = "Exam Runtime"
TAG_EXAM_RESULT = "Exam Result"
TAG_EXAM_INTEGRITY = "Exam Integrity"
TAG_EXAM_RETAKE = "Exam Retake"

_FlaggedQuestionsEnvelope = inline_serializer(
    name="FlaggedQuestionsEnvelope",
    fields={
        "success": drf_serializers.BooleanField(default=True),
        "message": drf_serializers.CharField(),
        "data": inline_serializer(
            name="FlaggedQuestionsData",
            fields={
                "session_id": drf_serializers.UUIDField(),
                "flagged_question_indexes": drf_serializers.ListField(
                    child=drf_serializers.IntegerField()
                ),
                "flagged_questions": drf_serializers.JSONField(),
            },
        ),
    },
)




# ---------------------------------------------------------------------------
# Read-side helpers
#
# Why these exist: every response that serializes an ExamSession / ExamResult /
# RetakeRequest hits 4–6 FK chains (exam_config, qualification, learner,
# invigilator, previous_result). Without prefetching, each response is N+1.
# Centralising the relation chains here keeps the views thin and guarantees
# every code path serializes through the same shape.
# ---------------------------------------------------------------------------
def _session_qs():
    return ExamSession.objects.select_related(
        "exam_config__qualification", "learner", "invigilator"
    )


def _result_qs():
    return ExamResult.objects.select_related(
        "learner", "exam_config", "qualification", "session"
    ).prefetch_related("session__violations")


def _retake_qs():
    return RetakeRequest.objects.select_related(
        "learner", "exam_config__qualification", "previous_result"
    )


def _notify_admins_retake_requested(req: RetakeRequest) -> None:
    """Fire-and-forget: email all active admins about a new retake request."""
    from django.conf import settings
    admin_url = f"{settings.FRONTEND_URL}/admin/retakes"
    admins = User.objects.filter(role="admin", is_active=True).values_list("email", flat=True)
    ctx = {
        "learner_name": req.learner.get_full_name() or req.learner.email,
        "exam_title": req.exam_config.title,
        "score": round(req.previous_result.score_percent, 1),
        "requested_at": req.requested_at.strftime("%d %b %Y %H:%M"),
        "admin_url": admin_url,
    }
    for email in admins:
        try:
            send_email("New resit request — action required", email, "retake_request_admin", ctx)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ExamConfig
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_EXAM_CONFIG],
        summary="List exam configurations",
        responses={200: envelope_list(ExamConfigSerializer, message_example="Exam configurations retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_EXAM_CONFIG],
        summary="Retrieve an exam configuration",
        responses={200: envelope_detail(ExamConfigSerializer, message_example="Exam configuration retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_EXAM_CONFIG],
        summary="Create an exam configuration",
        request=ExamConfigSerializer,
        responses={201: envelope_detail(ExamConfigSerializer, message_example="Exam configuration created successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    update=extend_schema(
        tags=[TAG_EXAM_CONFIG],
        summary="Replace an exam configuration",
        request=ExamConfigSerializer,
        responses={200: envelope_detail(ExamConfigSerializer, message_example="Exam configuration updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        tags=[TAG_EXAM_CONFIG],
        summary="Partially update an exam configuration",
        request=ExamConfigSerializer,
        responses={200: envelope_detail(ExamConfigSerializer, message_example="Exam configuration updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
)
class ExamConfigViewSet(viewsets.ModelViewSet):
    """
    Admin-facing exam blueprint CRUD.

    Frontend usage:
      - Admin exam setup screens use this endpoint to create and maintain the
        reusable exam configuration attached to a qualification.
      - Learner exam runtime does not call this endpoint directly.

    Query params (list):
      - search           : free-text against title / qualification title / code
      - status           : "draft" | "published"
      - exam_type        : "live"  | "mock"
      - qualification_id : UUID
      - strict_mode      : "true" | "false"
    """
    queryset = ExamConfig.objects.select_related("qualification").order_by("-created_at", "-id")
    serializer_class = ExamConfigSerializer
    permission_classes = [IsAdminOrReadOnlyForStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(qualification__title__icontains=search)
                | Q(qualification__code__icontains=search)
            )
        for field in ("status", "exam_type"):
            value = params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        if qid := params.get("qualification_id"):
            qs = qs.filter(qualification_id=qid)
        if strict := params.get("strict_mode"):
            qs = qs.filter(strict_mode=strict.lower() == "true")
        return qs

    # ----- list with summary block (mirrors InvigilatorViewSet) -----
    def _build_summary(self, qs):
        """Aggregate counters surfaced alongside the paginated results.

        Honors the same filters as list, so the summary reflects the current
        filter context (e.g. counts for a specific qualification).
        """
        agg = qs.aggregate(
            total=Count("id"),
            live=Count("id", filter=Q(exam_type="live")),
            mock=Count("id", filter=Q(exam_type="mock")),
            published=Count("id", filter=Q(status="published")),
            draft=Count("id", filter=Q(status="draft")),
            strict=Count("id", filter=Q(strict_mode=True)),
        )
        return {
            "total": agg["total"] or 0,
            "live": agg["live"] or 0,
            "mock": agg["mock"] or 0,
            "published": agg["published"] or 0,
            "draft": agg["draft"] or 0,
            "strict": agg["strict"] or 0,
        }

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary = self._build_summary(queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data = {
                "count": response.data.get("count"),
                "next": response.data.get("next"),
                "previous": response.data.get("previous"),
                "summary": summary,
                "results": response.data.get("results", []),
            }
            return response
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.ok(
            data={"summary": summary, "results": serializer.data},
        )

    # Kept as a standalone fallback for callers that only need the counters.
    @action(detail=False, methods=["get"], url_path="summary",
            permission_classes=[IsAdminOrReadOnlyForStaff])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return APIResponse.ok(
            data=self._build_summary(qs),
            message="Exam summary retrieved.",
        )


@extend_schema(
    tags=[TAG_EXAM_RUNTIME],
    summary="List published mock exams",
    responses={200: envelope_detail(ExamConfigSerializer(many=True), message_example="Mock exams retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
)
class MockExamListView(APIView):
    """Learner-visible published mock exams (no PIN required).

    For learners, the list is scoped to qualifications they're enrolled in
    (any non-withdrawn enrollment) — so a learner only sees the mocks for
    qualifications they actually take. Admin/invigilators see all published
    mocks.
    """
    permission_classes = [IsAuthenticated]
    def get(self, request):
        qs = (
            ExamConfig.objects
            .select_related("qualification")  # serializer reads qualification.title
            .filter(exam_type="mock", status="published")
        )
        if getattr(request.user, "role", None) == "learner":
            profile = getattr(request.user, "learner_profile", None)
            qualification_ids = (
                profile.enrollments
                .exclude(status="withdrawn")
                .values_list("qualification_id", flat=True)
            ) if profile else []
            qs = qs.filter(qualification_id__in=qualification_ids)
        return APIResponse.ok(
            data=ExamConfigSerializer(qs, many=True).data,
            message="Mock exams retrieved successfully.",
        )


@extend_schema(
    tags=[TAG_EXAM_RUNTIME],
    summary="Start a mock exam",
    responses={200: envelope_detail(ValidatePinResponseSerializer, message_example="Mock exam started successfully."), **DEFAULT_ERROR_RESPONSES},
)
class MockExamStartView(APIView):
    """Start a mock exam — generates an unmarked, throwaway question set."""
    permission_classes = [IsLearner]
    def get(self, request, exam_id):
        cfg = get_object_or_404(
            ExamConfig.objects.select_related("qualification"),
            id=exam_id, exam_type="mock", status="published",
        )
        # Mock exams DO NOT mark seen; no scenarios are snapshotted
        chosen, _ = select_questions_for_learner(
            exam_config=cfg, learner=request.user, mark_seen_session=None
        )
        return APIResponse.ok(
            data={
                "valid": True,
                "examQuestions": ExamQuestionSerializer(chosen, many=True, context={"request": request}).data,
                "timeLimitMinutes": cfg.time_limit_minutes,
                "examTitle": cfg.title,
                "qualificationTitle": cfg.qualification.title,
            },
            message="Mock exam started successfully.",
        )


# ---------------------------------------------------------------------------
# ExamSession (CRUD + workflow actions)
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="List exam sessions",
        responses={200: envelope_list(ExamSessionSerializer, message_example="Exam sessions retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Retrieve an exam session",
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Exam session retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    create=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Create a scheduled exam session",
        request=CreateExamSessionSerializer,
        responses={201: envelope_detail(ExamSessionSerializer, message_example="Exam session created successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    update_pin=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Update a session PIN",
        request=UpdateSessionPinSerializer,
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Session PIN updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    verify_id=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Mark session ID verification",
        request=inline_serializer(
            name="VerifySessionIdRequest",
            fields={"id_verified": drf_serializers.BooleanField(required=False, default=True)},
        ),
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Session ID verification updated successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    unlock=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Unlock a scheduled session",
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Session unlocked successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    complete=extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Complete a session",
        request=inline_serializer(
            name="CompleteSessionRequest",
            fields={
                "completed_successfully": drf_serializers.BooleanField(required=False, default=True),
                "incident_notes": drf_serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Session completed successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    save_draft=extend_schema(
        tags=[TAG_EXAM_RUNTIME],
        summary="Save an in-progress exam draft",
        request=SaveExamDraftSerializer,
        responses={200: envelope_action(
            {
                "sessionId": drf_serializers.UUIDField(),
                "answers": drf_serializers.ListField(child=drf_serializers.DictField()),
                "currentQuestionIndex": drf_serializers.IntegerField(),
                "flaggedQuestionIndexes": drf_serializers.ListField(child=drf_serializers.IntegerField()),
                "remainingSeconds": drf_serializers.IntegerField(),
                "updatedAt": drf_serializers.DateTimeField(),
            },
            name="ExamDraftSaved",
            message_example="Draft saved successfully.",
        ), **DEFAULT_ERROR_RESPONSES},
    ),
)
class ExamSessionViewSet(viewsets.ModelViewSet):
    """
    Session scheduling and invigilation workflow endpoints.

    Frontend usage:
      - Admin scheduling screens create sessions here.
      - Invigilator consoles use the session actions to verify identity,
        unlock, update PIN, and complete the session.
      - Learner runtime uses the draft action only for autosave.
    """
    queryset = ExamSession.objects.select_related(
        "exam_config", "exam_config__qualification", "learner", "invigilator"
    ).order_by("-created_at", "-id")
    serializer_class = ExamSessionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.role == "learner":
            return qs.filter(learner=u).order_by("-created_at", "-id")
        if u.role == "invigilator":
            return qs.filter(invigilator=u).order_by("-created_at", "-id")
        # Admin: optional ?learner_id / ?invigilator_id filters.
        if learner_id := self.request.query_params.get("learner_id"):
            qs = qs.filter(learner_id=learner_id)
        if invigilator_id := self.request.query_params.get("invigilator_id"):
            qs = qs.filter(invigilator_id=invigilator_id)
        return qs.order_by("-created_at", "-id")

    def get_permissions(self):
        if self.action == "create":
            return [IsAdmin()]
        return super().get_permissions()

    def _get_locked_session(self, pk):
        queryset = (
            self.filter_queryset(self.get_queryset())
            .select_related(None)
            .select_for_update()
        )
        session = get_object_or_404(queryset, pk=pk)
        self.check_object_permissions(self.request, session)
        return session

    def create(self, request, *args, **kwargs):
        s = CreateExamSessionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        cfg = get_object_or_404(ExamConfig, id=v["exam_config_id"])
        learner = get_object_or_404(User, id=v["learner_id"], role="learner")
        invigilator = get_object_or_404(User, id=v["invigilator_id"], role="invigilator")
        enrollment = None
        if v.get("enrollment_id"):
            enrollment = get_object_or_404(
                Enrollment.objects.select_related("learner__user", "qualification"),
                id=v["enrollment_id"],
            )
            if enrollment.learner.user_id != learner.id:
                return APIResponse.fail(
                    message="Enrollment does not belong to learner.",
                    errors={"enrollment_id": ["Enrollment does not belong to learner."]},
                    status=400,
                )
            if enrollment.status != EnrollmentStatus.ACTIVE:
                return APIResponse.fail(
                    message="Enrollment must be active.",
                    errors={"enrollment_id": ["Enrollment must be active."]},
                    status=400,
                )
            if enrollment.qualification_id != cfg.qualification_id:
                return APIResponse.fail(
                    message="Exam does not belong to enrollment qualification.",
                    errors={"exam_config_id": ["Exam does not belong to enrollment qualification."]},
                    status=400,
                )
        else:
            enrollment = (
                Enrollment.objects.select_related("learner__user", "qualification")
                .filter(
                    learner__user_id=learner.id,
                    qualification_id=cfg.qualification_id,
                    status=EnrollmentStatus.ACTIVE,
                )
                .order_by("-enrolled_at", "-created_at")
                .first()
            )
            if enrollment is None:
                return APIResponse.fail(
                    message="No active enrollment found for this learner and qualification.",
                    errors={"enrollment_id": ["No active enrollment found for this learner and qualification."]},
                    status=400,
                )
        previous_result = None
        if v.get("previous_result_id"):
            previous_result = get_object_or_404(ExamResult, id=v["previous_result_id"])

        # Auto-apply the learner's accepted reasonable adjustment unless
        # the caller has explicitly supplied overrides.
        ra_notes = v.get("reasonable_adjustments", "")
        ra_extra_time = v.get("extra_time_minutes")
        if not ra_notes and ra_extra_time is None:
            active_ra = (
                ReasonableAdjustment.objects
                .filter(learner__user=learner, accepted=True)
                .order_by("-created_at")
                .first()
            )
            if active_ra:
                ra_notes = active_ra.notes
                ra_extra_time = active_ra.extra_time_minutes

        session = create_scheduled_session(
            exam_config=cfg, learner=learner, invigilator=invigilator,
            scheduled_date=v["scheduled_date"], scheduled_time=v["scheduled_time"],
            enrollment=enrollment,
            pin=v.get("pin"),
            allow_immediate_start=v.get("allow_immediate_start", False),
            reasonable_adjustments=ra_notes,
            extra_time_minutes=ra_extra_time,
            previous_result=previous_result,
        )
        # Refetch with relations so the response serializer doesn't N+1 on
        # exam_config.qualification / learner / invigilator.
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Exam session created successfully.",
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["patch"], url_path="pin",
            permission_classes=[IsInvigilatorOrAdmin])
    def update_pin(self, request, pk=None):
        s = UpdateSessionPinSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            session = self._get_locked_session(pk)
            session.pin = s.validated_data["pin"]
            session.save(update_fields=["pin"])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session PIN updated successfully.",
        )

    @action(detail=True, methods=["patch"], url_path="verify-id",
            permission_classes=[IsInvigilatorOrAdmin])
    def verify_id(self, request, pk=None):
        with transaction.atomic():
            session = self._get_locked_session(pk)
            # Once the exam has actually started (or finished/cancelled), the
            # ID-confirmation tick is locked — an invigilator can no longer
            # un-confirm it. PIN validation already requires id_verified=True
            # before status can move past "scheduled" (see validate_pin /
            # unlock), so locking here also covers "unlock moves ID to locked".
            if session.status != "scheduled":
                return APIResponse.fail(
                    message="ID verification is locked once the exam has started and can no longer be changed.",
                    errors={"id_verified": ["Locked — the exam has already started"]},
                    status=400,
                )
            session.id_verified = bool(request.data.get("id_verified", True))
            session.save(update_fields=["id_verified"])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session ID verification updated successfully.",
        )

    @action(detail=True, methods=["post"], url_path="cancel",
            permission_classes=[IsAdmin])
    def cancel(self, request, pk=None):
        """Admin cancels a scheduled exam. No-op on already-completed sessions."""
        reason = (request.data.get("reason") or "").strip()
        with transaction.atomic():
            session = self._get_locked_session(pk)
            if session.status in {"completed", "cancelled"}:
                return APIResponse.fail(
                    message=f"Session is already {session.status}; cannot cancel.",
                    errors={"status": [f"Session is {session.status}"]},
                    status=400,
                )
            session.status = "cancelled"
            session.pin_active = False
            if reason:
                # Reuse incident_notes for the audit trail since there's no
                # dedicated cancellation reason column. Keep prior notes too.
                prefix = "[CANCELLED] "
                existing = (session.incident_notes or "").strip()
                session.incident_notes = (
                    f"{prefix}{reason}\n{existing}" if existing else f"{prefix}{reason}"
                )
            session.save(update_fields=["status", "pin_active", "incident_notes"])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session cancelled.",
        )

    @action(detail=True, methods=["post"], url_path="allow-immediate-start",
            permission_classes=[IsInvigilatorOrAdmin])
    def allow_immediate_start(self, request, pk=None):
        """Open the PIN window for an already-scheduled session immediately
        ("Sit Test Now").

        Used when the invigilator/admin needs to let a learner sit now (e.g.
        invigilator ready, learner present) without going through the schedule
        modal again. Recomputes pin_window_start to now and pin_window_end to
        now+duration. Invigilators are restricted to their own assigned
        sessions via _get_locked_session()'s row-level filtering.
        """
        with transaction.atomic():
            session = self._get_locked_session(pk)
            if session.status != "scheduled":
                return APIResponse.fail(
                    message=f"Session is {session.status}; cannot enable sit-now.",
                    errors={"status": [f"Session is {session.status}"]},
                    status=400,
                )
            pin_start, pin_end = _compute_pin_window(
                session.scheduled_date, session.scheduled_time, session.exam_config,
                extra_minutes=session.extra_time_minutes or 0,
                allow_immediate_start=True,
            )
            session.allow_immediate_start = True
            session.pin_window_start = pin_start
            session.pin_window_end = pin_end
            session.save(update_fields=[
                "allow_immediate_start", "pin_window_start", "pin_window_end",
            ])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session is now sit-now: PIN is valid immediately.",
        )

    @extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Reschedule a scheduled exam session",
        request=RescheduleExamSessionSerializer,
        responses={200: envelope_detail(ExamSessionSerializer, message_example="Exam session rescheduled successfully."), **DEFAULT_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["patch"], url_path="reschedule",
            permission_classes=[IsAdmin])
    def reschedule(self, request, pk=None):
        """Change exam, invigilator, date/time, or PIN on a scheduled session.

        Only allowed when status == "scheduled". If the exam config changes a
        new frozen question set is generated from the learner's unseen pool.
        """
        s = RescheduleExamSessionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        with transaction.atomic():
            session = self._get_locked_session(pk)
            if session.status != "scheduled":
                return APIResponse.fail(
                    message=f"Session is {session.status}; only 'scheduled' sessions can be rescheduled.",
                    errors={"status": [f"Session is {session.status}"]},
                    status=400,
                )

            new_cfg = get_object_or_404(ExamConfig, id=v["exam_config_id"])
            new_invigilator = get_object_or_404(User, id=v["invigilator_id"], role="invigilator")

            # Qualification must match the existing enrollment (if present)
            if session.enrollment_id:
                enrollment_qual_id = Enrollment.objects.values_list(
                    "qualification_id", flat=True
                ).get(pk=session.enrollment_id)
                if str(new_cfg.qualification_id) != str(enrollment_qual_id):
                    return APIResponse.fail(
                        message="Exam does not belong to the enrollment's qualification.",
                        errors={"exam_config_id": ["Exam must match the enrollment qualification."]},
                        status=400,
                    )

            update_fields = [
                "invigilator", "scheduled_date", "scheduled_time",
                "allow_immediate_start", "pin_window_start", "pin_window_end",
            ]

            # Regenerate question set when the exam config changes
            if str(v["exam_config_id"]) != str(session.exam_config_id):
                learner = User.objects.get(pk=session.learner_id)
                chosen, scenario_snapshot = select_questions_for_learner(
                    exam_config=new_cfg,
                    learner=learner,
                    mark_seen_session=session,
                )
                session.exam_config = new_cfg
                session.question_set = [str(q.id) for q in chosen]
                session.scenario_snapshot = scenario_snapshot
                update_fields.extend(["exam_config", "question_set", "scenario_snapshot"])

            session.invigilator = new_invigilator
            session.scheduled_date = v["scheduled_date"]
            session.scheduled_time = v["scheduled_time"]

            if v.get("pin"):
                session.pin = v["pin"]
                update_fields.append("pin")

            session.allow_immediate_start = False
            pin_start, pin_end = _compute_pin_window(
                session.scheduled_date,
                session.scheduled_time,
                new_cfg,
                extra_minutes=session.extra_time_minutes or 0,
                allow_immediate_start=False,
            )
            session.pin_window_start = pin_start
            session.pin_window_end = pin_end

            session.save(update_fields=update_fields)

        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Exam session rescheduled successfully.",
        )

    @action(detail=True, methods=["post"], url_path="unlock",
            permission_classes=[IsInvigilatorOrAdmin])
    def unlock(self, request, pk=None):
        with transaction.atomic():
            session = self._get_locked_session(pk)
            if not session.id_verified:
                return APIResponse.fail(
                    message="ID must be verified before unlocking the test.",
                    errors={"id_verified": ["ID verification required"]},
                    status=400,
                )
            session.pin_active = True
            if session.status == "scheduled":
                session.status = "in_progress"
            session.save(update_fields=["pin_active", "status"])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session unlocked successfully.",
        )

    @action(detail=True, methods=["post"], url_path="complete",
            permission_classes=[IsInvigilatorOrAdmin])
    def complete(self, request, pk=None):
        success = bool(request.data.get("completed_successfully", True))
        notes = request.data.get("incident_notes", "")
        with transaction.atomic():
            session = self._get_locked_session(pk)
            session.status = "completed"
            session.completed_successfully = success
            session.incident_notes = notes if not success else ""
            session.save(update_fields=["status", "completed_successfully", "incident_notes"])
        session = _session_qs().get(pk=session.pk)
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Session completed successfully.",
        )

    @extend_schema(
        tags=[TAG_EXAM_SESSION],
        summary="Retrieve learner-flagged questions for a session",
        responses={200: _FlaggedQuestionsEnvelope, **DEFAULT_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"], url_path="flagged-questions",
            permission_classes=[IsInvigilatorOrAdmin])
    def flagged_questions(self, request, pk=None):
        session = get_object_or_404(self.filter_queryset(self.get_queryset()), pk=pk)

        q_map = {
            str(q.id): q
            for q in Question.objects.filter(id__in=session.question_set or [])
        }
        ordered_questions = [q_map[qid] for qid in (session.question_set or []) if qid in q_map]

        rows = []
        for index in session.draft_flagged_question_indexes or []:
            question = ordered_questions[index] if 0 <= index < len(ordered_questions) else None
            rows.append(
                {
                    "index": index,
                    "question_id": question.id if question else None,
                    "question_text": question.question_text if question else "",
                }
            )

        return APIResponse.ok(
            data={
                "session_id": session.id,
                "flagged_question_indexes": session.draft_flagged_question_indexes or [],
                "flagged_questions": rows,
            },
            message="Flagged questions retrieved successfully.",
        )

    @action(detail=True, methods=["patch"], url_path="draft",
            permission_classes=[IsLearner, IsSessionLearnerOwner])
    def save_draft(self, request, pk=None):
        with transaction.atomic():
            session = self._get_locked_session(pk)

            if session.status not in {"scheduled", "in_progress"}:
                return APIResponse.fail(
                    message="Session is not active.",
                    errors={"session_id": ["Session is not active"]},
                    status=400,
                )

            s = SaveExamDraftSerializer(data={**request.data, "session_id": pk})
            s.is_valid(raise_exception=True)
            v = s.validated_data

            frozen = set(session.question_set or [])
            if not frozen:
                return APIResponse.fail(
                    message="Session has no frozen question set.",
                    errors={"session_id": ["No frozen question set"]},
                    status=400,
                )
            for a in v["answers"]:
                if str(a.get("questionId")) not in frozen:
                    return APIResponse.fail(
                        message="Answer references a question outside this session.",
                        errors={"answers": ["Invalid question reference"]},
                        status=400,
                    )

            now = timezone.now()
            session.draft_answers = v["answers"]
            session.draft_current_question_index = v["current_question_index"]
            session.draft_flagged_question_indexes = v["flagged_question_indexes"]
            session.draft_remaining_seconds = v["remaining_seconds"]
            session.draft_updated_at = now
            update_fields = [
                "draft_answers",
                "draft_current_question_index",
                "draft_flagged_question_indexes",
                "draft_remaining_seconds",
                "draft_updated_at",
            ]
            if session.status == "scheduled":
                session.status = "in_progress"
                update_fields.append("status")
            if session.started_at is None:
                # Falls back to here for sessions the invigilator already
                # unlocked (status flipped to "in_progress" before the
                # learner entered their PIN), so time_taken_seconds isn't
                # always 0 at submission.
                session.started_at = now
                update_fields.append("started_at")
            session.save(update_fields=update_fields)

        return APIResponse.ok(
            data={
                "sessionId": str(session.id),
                "answers": session.draft_answers,
                "currentQuestionIndex": session.draft_current_question_index,
                "flaggedQuestionIndexes": session.draft_flagged_question_indexes,
                "remainingSeconds": session.draft_remaining_seconds,
                "updatedAt": session.draft_updated_at.isoformat(),
            },
            message="Draft saved successfully.",
        )


# ---------------------------------------------------------------------------
# Validate PIN (gateway into exam runtime)
# ---------------------------------------------------------------------------
@extend_schema(
    tags=[TAG_EXAM_RUNTIME],
    summary="Validate learner PIN and open the frozen exam session",
    request=ValidatePinRequestSerializer,
    responses={200: envelope_detail(ValidatePinResponseSerializer, message_example="PIN validated successfully."), **DEFAULT_ERROR_RESPONSES},
)
class ValidatePinView(APIView):
    permission_classes = [IsLearner]

    def post(self, request):
        s = ValidatePinRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        with transaction.atomic():
            session = get_object_or_404(
                # select_related avoids the separate exam_config / qualification
                # lookups below; of=("self",) keeps the row lock scoped to
                # exam_session only, so concurrent learners sharing the same
                # exam_config/qualification aren't serialized against each other.
                ExamSession.objects
                    .select_related("exam_config__qualification")
                    .select_for_update(of=("self",)),
                id=v["session_id"],
            )
            if session.learner_id != request.user.id:
                return APIResponse.fail(
                    message="Not your session.",
                    errors={"session_id": ["Invalid session"]},
                    status=403
                )
            if session.pin != v["pin"] or not session.pin_active:
                return APIResponse.fail(
                    message="Invalid PIN",
                    errors={"pin": ["Invalid PIN"]},
                    status=400
                )
            if session.status == "completed":
                return APIResponse.fail(
                    message="This exam has already been completed.",
                    errors={"session_id": ["Exam already completed"]},
                    status=400
                )

            if not session.id_verified:
                return APIResponse.fail(
                    message="Your identity has not yet been verified by your invigilator. Please inform your invigilator and ask them to verify your ID before you can begin the exam.",
                    errors={"id_verified": ["ID verification required"]},
                    status=403
                )

            now = timezone.now()
            if session.pin_window_start and session.pin_window_end:
                if now < session.pin_window_start or now > session.pin_window_end:
                    start = session.pin_window_start.isoformat()
                    return APIResponse.fail(
                        message=f"PIN is only valid from 5 minutes before the scheduled time ({start}) and expires when the test time elapses.",
                        errors={"pin": ["PIN not valid at this time"]},
                        status=400
                    )

            if not session.question_set:
                return APIResponse.fail(
                    message="Exam session has no frozen question set. Ask an admin to recreate the session.",
                    errors={"session_id": ["Session not properly configured"]},
                    status=400
                )

            # Load questions in stored order
            q_map = {str(q.id): q for q in Question.objects.filter(id__in=session.question_set)}
            ordered = [q_map[qid] for qid in session.question_set if qid in q_map]
            if len(ordered) != session.exam_config.questions_per_exam:
                return APIResponse.fail(
                    message="Frozen question set is invalid. Ask an admin to recreate the session.",
                    errors={"session_id": ["Session configuration error"]},
                    status=400
                )

            pin_update_fields = []
            if session.status == "scheduled":
                session.status = "in_progress"
                pin_update_fields.append("status")
            if session.started_at is None:
                # Falls back to here for sessions the invigilator already
                # unlocked (status flipped to "in_progress" before the
                # learner entered their PIN), so time_taken_seconds isn't
                # always 0 at submission.
                session.started_at = now
                pin_update_fields.append("started_at")
            if pin_update_fields:
                session.save(update_fields=pin_update_fields)

            draft = None
            if session.draft_updated_at:
                draft = {
                    "sessionId": str(session.id),
                    "answers": session.draft_answers,
                    "currentQuestionIndex": session.draft_current_question_index,
                    "flaggedQuestionIndexes": session.draft_flagged_question_indexes,
                    "remainingSeconds": session.draft_remaining_seconds,
                    "updatedAt": session.draft_updated_at.isoformat(),
                }

        # Build scenarios dict: resolve image paths to absolute URLs
        scenarios = {}
        for sid, snap in (session.scenario_snapshot or {}).items():
            image_url = None
            if snap.get("imagePath"):
                from django.conf import settings as django_settings
                from urllib.parse import urljoin
                image_url = request.build_absolute_uri(
                    urljoin(django_settings.MEDIA_URL, snap["imagePath"])
                )
            scenarios[sid] = {
                "title": snap["title"],
                "body": snap["body"],
                "imageUrl": image_url,
            }

        return APIResponse.ok(
            data={
                "valid": True,
                "examQuestions": ExamQuestionSerializer(ordered, many=True, context={"request": request}).data,
                "scenarios": scenarios,
                "timeLimitMinutes": session.exam_config.time_limit_minutes
                                    + (session.extra_time_minutes or 0),
                "examTitle": session.exam_config.title,
                "qualificationTitle": session.exam_config.qualification.title,
                "draft": draft,
            },
            message="PIN validated successfully.",
        )


# ---------------------------------------------------------------------------
# Submit Exam
# ---------------------------------------------------------------------------
@extend_schema(
    tags=[TAG_EXAM_RUNTIME],
    summary="Submit an exam session",
    request=SubmitExamSerializer,
    responses={201: envelope_detail(ExamResultSerializer, message_example="Exam submitted successfully."), **DEFAULT_ERROR_RESPONSES},
)
class SubmitExamView(APIView):
    permission_classes = [IsLearner]

    @transaction.atomic
    def post(self, request, session_id):
        session = get_object_or_404(
            # select_related avoids the lazy loads on exam_config/qualification,
            # learner, and invigilator below and in ExamResultSerializer;
            # of=("self",) keeps the row lock scoped to exam_session only.
            ExamSession.objects
                .select_related("exam_config__qualification", "learner", "invigilator")
                .select_for_update(of=("self",)),
            id=session_id,
        )
        if session.learner_id != request.user.id:
            return APIResponse.fail(
                message="Forbidden",
                errors={"session_id": ["Access denied"]},
                status=403
            )
        if session.status not in {"in_progress", "scheduled"}:
            return APIResponse.fail(
                message="Session not in progress.",
                errors={"session_id": ["Invalid session status"]},
                status=400
            )

        s = SubmitExamSerializer(data={**request.data, "session_id": session_id})
        s.is_valid(raise_exception=True)
        answers = s.validated_data["answers"]

        frozen = set(session.question_set or [])
        for a in answers:
            if str(a["questionId"]) not in frozen:
                return APIResponse.fail(
                    message="Submission contains a question outside this session.",
                    errors={"answers": ["Invalid question in submission"]},
                    status=400
                )

        if ExamResult.objects.filter(session=session).exists():
            existing = ExamResult.objects.select_related(
                "learner", "exam_config", "qualification", "session"
            ).prefetch_related("session__violations").get(session=session)
            return APIResponse.ok(
                data=ExamResultSerializer(existing).data,
                message="Exam already submitted.",
                status=200,
            )

        scoring = score_submission(session=session, answers=answers)

        User.objects.select_for_update().get(pk=session.learner_id)
        attempt_number = ExamResult.objects.filter(
            learner=session.learner, exam_config=session.exam_config
        ).count() + 1

        time_taken = 0
        if session.started_at:
            time_taken = int((timezone.now() - session.started_at).total_seconds())

        result = ExamResult.objects.create(
            session=session,
            learner=session.learner,
            exam_config=session.exam_config,
            qualification=session.exam_config.qualification,
            score_percent=scoring["score_percent"],
            correct_count=scoring["correct_count"],
            total_questions=scoring["total_questions"],
            grade=scoring["grade"],
            passed=scoring["passed"],
            time_taken_seconds=time_taken,
            violation_count=session.violations.count(),
            question_ids=session.question_set,
            answers=answers,
            invigilator_name=f"{session.invigilator.first_name} {session.invigilator.last_name}".strip(),
            reasonable_adjustments=session.reasonable_adjustments or "",
            attempt_number=attempt_number,
            exam_date=session.scheduled_date,
        )
        session.status = "completed"
        session.submitted_at = timezone.now()
        session.save(update_fields=["status", "submitted_at"])

        return APIResponse.ok(
            data=ExamResultSerializer(result).data,
            message="Exam submitted successfully.",
            status=201
        )


# ---------------------------------------------------------------------------
# Integrity violations
# ---------------------------------------------------------------------------
@extend_schema(
    tags=[TAG_EXAM_INTEGRITY],
    summary="Report an integrity violation",
    request=ReportViolationSerializer,
    responses={200: envelope_action(
        {"strikeCount": drf_serializers.IntegerField()},
        name="ViolationReported",
        message_example="Violation reported successfully.",
    ), **DEFAULT_ERROR_RESPONSES},
)
class ReportViolationView(APIView):
    permission_classes = [IsLearner]

    def post(self, request):
        s = ReportViolationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        with transaction.atomic():
            session = get_object_or_404(
                ExamSession.objects.select_for_update(),
                id=v["session_id"],
            )
            if session.learner_id != request.user.id:
                return APIResponse.fail(
                    message="Forbidden",
                    errors={"session_id": ["Access denied"]},
                    status=403
                )
            if session.status != "in_progress":
                return APIResponse.fail(
                    message="Session not active.",
                    errors={"session_id": ["Session not active"]},
                    status=400
                )
            IntegrityViolation.objects.create(session=session, **v["violation"])
            strike_count = session.violations.count()
        return APIResponse.ok(
            data={"strikeCount": strike_count},
            message="Violation reported successfully.",
        )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_EXAM_RESULT],
        summary="List exam results",
        responses={200: envelope_list(ExamResultSerializer, message_example="Exam results retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
    retrieve=extend_schema(
        tags=[TAG_EXAM_RESULT],
        summary="Retrieve an exam result",
        responses={200: envelope_detail(ExamResultSerializer, message_example="Exam result retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
)
class ExamResultViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only result endpoints for admin, invigilator, and learner result views."""
    queryset = ExamResult.objects.select_related(
        "learner", "learner__learner_profile", "exam_config", "qualification", "session"
    ).prefetch_related("session__violations").order_by("-submitted_at", "-id")
    serializer_class = ExamResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.role == "learner":
            qs = qs.filter(learner=u)
        elif u.role == "invigilator":
            qs = qs.filter(session__invigilator=u)
        if learner_id := self.request.query_params.get("learner_id"):
            qs = qs.filter(learner_id=learner_id)
        if qualification_id := self.request.query_params.get("qualification_id"):
            qs = qs.filter(qualification_id=qualification_id)
        if exam_config_id := self.request.query_params.get("exam_config_id"):
            qs = qs.filter(exam_config_id=exam_config_id)
        if grade := self.request.query_params.get("grade"):
            qs = qs.filter(grade=grade)
        if search := self.request.query_params.get("search", "").strip():
            qs = qs.filter(
                Q(learner__first_name__icontains=search)
                | Q(learner__last_name__icontains=search)
                | Q(learner__learner_profile__uln__icontains=search)
                | Q(exam_config__title__icontains=search)
            )
        return qs

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _uln(result):
        profile = getattr(result.learner, "learner_profile", None)
        return profile.uln if profile and profile.uln else ""

    @staticmethod
    def _row(i, r):
        minutes = round(r.time_taken_seconds / 60, 1) if r.time_taken_seconds else 0
        return [
            str(i),
            f"{r.learner.first_name} {r.learner.last_name}".strip(),
            ExamResultViewSet._uln(r),
            r.qualification.title,
            r.exam_config.title,
            r.exam_date.strftime("%d/%m/%Y") if r.exam_date else "",
            f"{r.score_percent}%",
            r.grade.replace("_", " ").title(),
            "Yes" if r.passed else "No",
            str(minutes),
            str(r.violation_count),
            str(r.attempt_number),
        ]

    # ── CSV export ────────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="exam_results.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "#", "Learner Name", "ULN", "Qualification", "Exam",
            "Date", "Score %", "Grade", "Passed",
            "Time (min)", "Violations", "Attempt #",
        ])
        for i, r in enumerate(self.get_queryset(), 1):
            writer.writerow(self._row(i, r))
        return response

    # ── PDF export ────────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request):
        import os
        from django.conf import settings
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image

        BLUE      = rl_colors.HexColor("#1A4D58")
        BLUE_DARK = rl_colors.HexColor("#0F2F38")
        BLACK     = rl_colors.HexColor("#0F172A")
        WHITE     = rl_colors.white

        results = list(self.get_queryset())
        total        = len(results)
        passed_count = sum(1 for r in results if r.passed)
        pass_rate    = round(passed_count / total * 100) if total else 0
        avg_score    = round(sum(r.score_percent for r in results) / total) if total else 0
        distinctions = sum(1 for r in results if r.grade == "distinction")

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A4),
            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
            topMargin=0.4 * cm, bottomMargin=1.0 * cm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle", parent=styles["Title"],
            textColor=BLACK, fontSize=16, spaceAfter=4, alignment=1,
        )

        elements = []

        # ── Centred header: blue logo above title ────────────────────────────
        logo_path = os.path.join(settings.BASE_DIR, "static", "marksheet", "logo_blue.png")
        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=3.5 * cm, height=2.5 * cm)
        else:
            logo_img = Spacer(3.5 * cm, 2.5 * cm)

        header_data = [[logo_img], [Paragraph("Exam Results Report", title_style)]]
        header_table = Table(header_data, colWidths=[27.3 * cm])
        header_table.setStyle(TableStyle([
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ]))
        elements += [header_table, Spacer(1, 0.2 * cm)]

        # ── Summary stats ─────────────────────────────────────────────────────
        stats_table = Table(
            [
                ["Total Attempts", "Pass Rate", "Average Score", "Distinctions"],
                [str(total), f"{pass_rate}%", f"{avg_score}%", str(distinctions)],
            ],
            colWidths=[5 * cm] * 4,
        )
        stats_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 10),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TEXTCOLOR",     (0, 1), (-1, 1), BLACK),
            ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
            ("BACKGROUND",    (0, 1), (-1, 1), WHITE),
            ("BOX",           (0, 0), (-1, -1), 0.8, BLUE),
            ("INNERGRID",     (0, 0), (-1, -1), 0.5, BLUE),
            ("INNERGRID",     (0, 0), (-1, 0),  0.5, WHITE),  # white borders on header row
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements += [stats_table, Spacer(1, 0.5 * cm)]

        # ── Results table ─────────────────────────────────────────────────────
        col_headers = [
            "#", "Learner Name", "ULN", "Qualification", "Exam",
            "Date", "Score %", "Grade", "Passed",
            "Time\n(min)", "Violations", "Attempt",
        ]
        col_widths = [
            0.7*cm, 3.8*cm, 2.2*cm, 4.2*cm, 3.8*cm,
            2.2*cm, 1.7*cm, 2.4*cm, 1.5*cm,
            1.7*cm, 1.9*cm, 1.6*cm,
        ]
        rows = [col_headers] + [self._row(i, r) for i, r in enumerate(results, 1)]
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            # Data rows — white background, black text
            ("BACKGROUND",    (0, 1), (-1, -1), WHITE),
            ("TEXTCOLOR",     (0, 1), (-1, -1), BLACK),
            ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BOX",           (0, 0), (-1, -1), 0.8, BLUE),
            ("INNERGRID",     (0, 0), (-1, -1), 0.4, BLUE),
            ("INNERGRID",     (0, 0), (-1, 0),  0.4, WHITE),  # white borders on header row
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)

        doc.build(elements)
        buf.seek(0)
        response = HttpResponse(buf.read(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="exam_results.pdf"'
        return response

    # ── Individual marksheet ──────────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="marksheet")
    def marksheet(self, request, pk=None):
        from apps.reports.marksheet import render_marksheet

        result = self.get_object()
        pdf_bytes = render_marksheet(result)
        last = result.learner.last_name.replace(" ", "_")
        fname = f"marksheet_{last}_{result.exam_date}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{fname}"'
        return response



# ---------------------------------------------------------------------------
# Retakes / Resits
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(
        tags=[TAG_EXAM_RETAKE],
        summary="List retake requests",
        responses={200: envelope_list(RetakeRequestSerializer, message_example="Retake requests retrieved successfully."), **DEFAULT_ERROR_RESPONSES},
    ),
)
class RetakeRequestViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only retake request listing for learner and admin retake queues."""
    queryset = RetakeRequest.objects.select_related(
        "learner", "exam_config", "exam_config__qualification", "previous_result",
        "reviewed_by", "new_session",
    )
    serializer_class = RetakeRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if u.role == "learner":
            qs = qs.filter(learner=u)
        elif u.role == "invigilator":
            qs = qs.filter(previous_result__session__invigilator=u)
        if status_q := self.request.query_params.get("status"):
            qs = qs.filter(status=status_q)
        if lid := self.request.query_params.get("learner_id"):
            qs = qs.filter(learner_id=lid)
        if previous_result_id := self.request.query_params.get("previous_result_id"):
            qs = qs.filter(previous_result_id=previous_result_id)
        return qs.annotate(
            activity_at=Coalesce("reviewed_at", "requested_at"),
        ).order_by("-activity_at", "-requested_at")


@extend_schema(
    tags=[TAG_EXAM_RETAKE],
    summary="Create a retake request",
    request=CreateRetakeRequestSerializer,
    responses={201: envelope_detail(RetakeRequestSerializer, message_example="Retake request submitted successfully."), **DEFAULT_ERROR_RESPONSES},
)
class RequestRetakeView(APIView):
    permission_classes = [IsLearner]
    def post(self, request):
        s = CreateRetakeRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        if str(v["learner_id"]) != str(request.user.id):
            return APIResponse.fail(
                message="Forbidden",
                errors={"learner_id": ["Access denied"]},
                status=403
            )
        with transaction.atomic():
            prev = get_object_or_404(
                ExamResult.objects.select_for_update(),
                id=v["previous_result_id"],
                learner=request.user,
            )
            cfg = get_object_or_404(ExamConfig, id=v["exam_config_id"])
            if RetakeRequest.objects.filter(previous_result=prev, status="pending").exists():
                return APIResponse.fail(
                    message="A pending retake already exists for this result.",
                    errors={"previous_result_id": ["Duplicate request"]},
                    status=400
                )
            req = RetakeRequest.objects.create(
                learner=request.user, exam_config=cfg, previous_result=prev,
            )
        try:
            _notify_admins_retake_requested(req)
        except Exception:
            pass
        return APIResponse.ok(
            data=RetakeRequestSerializer(req).data,
            message="Retake request submitted successfully.",
            status=201
        )


class ApproveRetakeView(APIView):
    permission_classes = [IsAdmin]
    serializer_class = RetakeRequestSerializer

    @extend_schema(
        tags=[TAG_EXAM_RETAKE],
        summary="Approve a retake request",
        responses={200: envelope_detail(RetakeRequestSerializer, message_example="Retake request approved successfully."), **DEFAULT_ERROR_RESPONSES},
    )
    def put(self, request, retake_id):
        with transaction.atomic():
            req = get_object_or_404(
                RetakeRequest.objects.select_for_update(),
                id=retake_id,
                status="pending",
            )
            req.status = "approved"
            req.reviewed_at = timezone.now()
            req.reviewed_by = request.user
            req.save(update_fields=["status", "reviewed_at", "reviewed_by"])
        try:
            from django.conf import settings
            send_email(
                "Your resit request has been approved",
                req.learner.email,
                "retake_approved",
                {
                    "first_name": req.learner.first_name or req.learner.email,
                    "exam_title": req.exam_config.title,
                    "score": round(req.previous_result.score_percent, 1),
                    "dashboard_url": f"{settings.FRONTEND_URL}/learner/dashboard",
                },
            )
        except Exception:
            pass
        return APIResponse.ok(
            data=RetakeRequestSerializer(req).data,
            message="Retake request approved successfully.",
        )


@extend_schema(
    tags=[TAG_EXAM_RETAKE],
    summary="Deny a retake request",
    request=DenyRetakeSerializer,
    responses={200: envelope_detail(RetakeRequestSerializer, message_example="Retake request denied successfully."), **DEFAULT_ERROR_RESPONSES},
)
class DenyRetakeView(APIView):
    permission_classes = [IsAdmin]
    def put(self, request, retake_id):
        s = DenyRetakeSerializer(data=request.data); s.is_valid(raise_exception=True)
        with transaction.atomic():
            req = get_object_or_404(
                RetakeRequest.objects.select_for_update(),
                id=retake_id,
                status="pending",
            )
            req.status = "denied"
            req.reviewed_at = timezone.now()
            req.reviewed_by = request.user
            req.denial_reason = s.validated_data["denial_reason"]
            req.save(update_fields=["status", "reviewed_at", "reviewed_by", "denial_reason"])
        try:
            from django.conf import settings
            send_email(
                "Update on your resit request",
                req.learner.email,
                "retake_denied",
                {
                    "first_name": req.learner.first_name or req.learner.email,
                    "exam_title": req.exam_config.title,
                    "score": round(req.previous_result.score_percent, 1),
                    "denial_reason": req.denial_reason,
                },
            )
        except Exception:
            pass
        return APIResponse.ok(
            data=RetakeRequestSerializer(req).data,
            message="Retake request denied successfully.",
        )


@extend_schema(
    tags=[TAG_EXAM_RETAKE],
    summary="Create a resit session from a previous result",
    request=CreateResitSessionSerializer,
    responses={201: envelope_detail(ExamSessionSerializer, message_example="Resit session created successfully."), **DEFAULT_ERROR_RESPONSES},
)
class CreateResitSessionView(APIView):
    """
    Invigilator-driven: take a previous_result, verify resit eligibility,
    create a fresh ExamSession with a brand-new unseen question set.
    """
    permission_classes = [IsInvigilatorOrAdmin]

    def post(self, request):
        s = CreateResitSessionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        with transaction.atomic():
            prev = get_object_or_404(
                ExamResult.objects.select_for_update(),
                id=v["previous_result_id"],
            )
            retake_request = (
                RetakeRequest.objects
                .select_for_update()
                .filter(previous_result=prev, status="pending")
                .order_by("-requested_at")
                .first()
            )
            cfg = prev.exam_config
            if not is_resit_eligible(prev.score_percent, cfg.grade_pass):
                return APIResponse.fail(
                    message="Learner is outside the 10% resit eligibility window.",
                    errors={"previous_result_id": ["Not eligible for resit"]},
                    status=400
                )

            invigilator = get_object_or_404(User, id=v["invigilator_id"], role="invigilator")

            scheduled_date = v.get("scheduled_date") or (timezone.now().date() + timedelta(days=1))
            scheduled_time = v.get("scheduled_time") or datetime.strptime("09:00", "%H:%M").time()

            session = create_scheduled_session(
                exam_config=cfg,
                learner=prev.learner,
                invigilator=invigilator,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                enrollment=(
                    Enrollment.objects.select_related("learner__user", "qualification")
                    .filter(
                        learner__user_id=prev.learner_id,
                        qualification_id=cfg.qualification_id,
                        status=EnrollmentStatus.ACTIVE,
                    )
                    .order_by("-enrolled_at", "-created_at")
                    .first()
                ),
                previous_result=prev,
            )
            if retake_request is not None:
                retake_request.status = "approved"
                retake_request.reviewed_at = timezone.now()
                retake_request.reviewed_by = request.user
                retake_request.new_session = session
                retake_request.denial_reason = ""
                retake_request.save(
                    update_fields=[
                        "status",
                        "reviewed_at",
                        "reviewed_by",
                        "new_session",
                        "denial_reason",
                    ]
                )
            session = _session_qs().get(pk=session.pk)
        try:
            from django.conf import settings
            learner = prev.learner
            send_email(
                "Your resit has been scheduled",
                learner.email,
                "resit_scheduled",
                {
                    "first_name": learner.first_name or learner.email,
                    "exam_title": cfg.title,
                    "scheduled_date": scheduled_date.strftime("%d %b %Y"),
                    "scheduled_time": scheduled_time.strftime("%H:%M"),
                    "invigilator_name": invigilator.get_full_name() or invigilator.email,
                    "dashboard_url": f"{settings.FRONTEND_URL}/learner/dashboard",
                },
            )
        except Exception:
            pass
        return APIResponse.ok(
            data=ExamSessionSerializer(session).data,
            message="Resit session created successfully.",
            status=201
        )


_GeneratePinEnvelope = inline_serializer(
    name="GeneratePinEnvelope",
    fields={
        "success": drf_serializers.BooleanField(default=True),
        "message": drf_serializers.CharField(),
        "data": inline_serializer(
            name="GeneratePinData",
            fields={"pin": drf_serializers.RegexField(r"^\d{6}$")},
        ),
    },
)



@extend_schema(
    tags=["Exam"],
    summary="Generate a fresh 6-digit exam PIN",
    responses={200: _GeneratePinEnvelope, **DEFAULT_ERROR_RESPONSES},
)
class GenerateExamPinView(APIView):
    """Returns a fresh 6-digit PIN. Nothing persisted — pure preview."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return APIResponse.ok(data={"pin": _generate_pin()})


class ExamDropdownViewSet(ListAPIView):
    """
    Provides a minimal list of exams for dropdowns and selectors.

    This is intentionally not a full ModelViewSet to avoid accidentally
    exposing create/update/delete endpoints on the ExamConfig model.
    """
    queryset = ExamConfig.objects.select_related("qualification").order_by("title", "version_number")
    serializer_class = ExamConfigDropdownSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        qualification_id = (
            self.request.query_params.get("qualification_id")
            or self.request.query_params.get("qualification")
        )
        if qualification_id:
            qs = qs.filter(qualification_id=qualification_id)
        status_value = self.request.query_params.get("status")
        if status_value:
            qs = qs.filter(status=status_value)
        return qs


class ExamByQualificationDropdownView(ExamDropdownViewSet):
    """
    Alias endpoint for exam dropdowns driven by a selected qualification.

    Example:
      GET /api/exams/by-qualification/dropdown/?qualification_id=<uuid>

    If a qualification has 3 exams configured, this returns all 3.
    """
