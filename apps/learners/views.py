"""
apps/learners/views.py
────────────────────────────────────────────────────────────
All endpoints return APIResponse-wrapped JSON.
camelCase ↔ snake_case handled at the serializer level.

Endpoints:

  Admin (AdminLearners.tsx)
    GET    /api/learners/                         list + search + filter
    POST   /api/learners/                         register learner + enroll
    GET    /api/learners/{user_id}/               detail
    PATCH  /api/learners/{user_id}/               update
    POST   /api/learners/{user_id}/activate/      reactivate
    POST   /api/learners/{user_id}/deactivate/    deactivate
    POST   /api/learners/{user_id}/resend-welcome/  resend welcome email

  Invigilator (InvigilatorDashboard.tsx — verify ID)
    GET    /api/learners/by-uln/{uln}/

  Enrollments
    GET    /api/enrollments/                      admin list
    POST   /api/enrollments/                      admin create
    PATCH  /api/enrollments/{id}/                 admin update (status, withdrawal)
    GET    /api/me/enrollments/                   learner self

  Reasonable Adjustments (AdminAdjustments.tsx)
    GET    /api/reasonable-adjustments/
    POST   /api/reasonable-adjustments/
    PATCH  /api/reasonable-adjustments/{id}/
"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import generics, serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer, OpenApiParameter

from core.responses import APIResponse
from core.email import send_email
from core.schemas import DEFAULT_ERROR_RESPONSES, EmptyEnvelope, envelope_array, envelope_detail, envelope_list

from apps.users.models import LearnerProfile, Role, generate_uln

from .models import Enrollment, ReasonableAdjustment
from .serializers import (
    LearnerSerializer,
    RegisterLearnerSerializer,
    UpdateLearnerSerializer,
    EnrollmentSerializer,
    CreateEnrollmentSerializer,
    ReasonableAdjustmentSerializer,
    CreateReasonableAdjustmentSerializer,
)
from .permissions import IsAdmin, IsAdminOrReadOnlyStaff, IsSelfLearner
from .filters import LearnerFilter


# ─────────────────────────────────────────────────────────────
# Learners
# ─────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=["Learners"], responses={200: envelope_list(LearnerSerializer), **DEFAULT_ERROR_RESPONSES}),
    retrieve=extend_schema(tags=["Learners"], responses={200: envelope_detail(LearnerSerializer), **DEFAULT_ERROR_RESPONSES}),
    create=extend_schema(tags=["Learners"], request=RegisterLearnerSerializer, responses={201: envelope_detail(LearnerSerializer), **DEFAULT_ERROR_RESPONSES}),
    partial_update=extend_schema(tags=["Learners"], request=UpdateLearnerSerializer, responses={200: envelope_detail(LearnerSerializer), **DEFAULT_ERROR_RESPONSES}),
    activate=extend_schema(tags=["Learners"], responses={200: EmptyEnvelope, **DEFAULT_ERROR_RESPONSES}),
    deactivate=extend_schema(tags=["Learners"], responses={200: EmptyEnvelope, **DEFAULT_ERROR_RESPONSES}),
    resend_welcome=extend_schema(tags=["Learners"], responses={200: EmptyEnvelope, **DEFAULT_ERROR_RESPONSES}),
)
class LearnerViewSet(viewsets.GenericViewSet):
    """
    URL key is the learner's `user_id` (UUID) — matches what the React
    `Learner.id` field contains.
    """
    queryset = LearnerProfile.objects.select_related("user").prefetch_related("enrollments__qualification")
    permission_classes = [IsAdminOrReadOnlyStaff]
    filter_backends = [DjangoFilterBackend]
    filterset_class = LearnerFilter
    lookup_field = "user_id"

    def get_serializer_class(self):
        if self.action == "create":
            return RegisterLearnerSerializer
        if self.action in ("partial_update", "update"):
            return UpdateLearnerSerializer
        return LearnerSerializer

    def list(self, request):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        data = LearnerSerializer(page or qs, many=True).data
        if page is not None:
            return self.get_paginated_response(data)
        return APIResponse.ok(data=data, message="Learners retrieved")

    def retrieve(self, request, user_id=None):
        profile = get_object_or_404(self.get_queryset(), user_id=user_id)
        return APIResponse.ok(data=LearnerSerializer(profile).data)

    def create(self, request):
        if request.user.role != Role.ADMIN:
            return APIResponse.fail(message="Forbidden", status=status.HTTP_403_FORBIDDEN)

        serializer = RegisterLearnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        # Welcome email — non-blocking failure
        try:
            send_email(
                subject="Welcome to Lead Edge Exam Centre",
                to_email=profile.user.email,
                template_name="learner_welcome",
                context={
                    "first_name": profile.user.first_name,
                    "learner_id": profile.learner_id,
                    "uln": profile.uln,
                    "login_url": f"{settings.FRONTEND_URL}/test-centre",
                },
            )
        except Exception:
            pass

        return APIResponse.ok(
            data=LearnerSerializer(profile).data,
            message="Learner registered successfully",
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, user_id=None):
        if request.user.role != Role.ADMIN:
            return APIResponse.fail(message="Forbidden", status=status.HTTP_403_FORBIDDEN)
        profile = get_object_or_404(self.get_queryset(), user_id=user_id)
        serializer = UpdateLearnerSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return APIResponse.ok(data=LearnerSerializer(profile).data, message="Learner updated")

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def activate(self, request, user_id=None):
        profile = get_object_or_404(self.get_queryset(), user_id=user_id)
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])
        return APIResponse.ok(message="Learner activated")

    @action(detail=True, methods=["post"], permission_classes=[IsAdmin])
    def deactivate(self, request, user_id=None):
        profile = get_object_or_404(self.get_queryset(), user_id=user_id)
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        return APIResponse.ok(message="Learner deactivated")

    @action(detail=True, methods=["post"], url_path="resend-welcome", permission_classes=[IsAdmin])
    def resend_welcome(self, request, user_id=None):
        profile = get_object_or_404(self.get_queryset(), user_id=user_id)
        send_email(
            subject="Welcome to Lead Edge Exam Centre",
            to_email=profile.user.email,
            template_name="learner_welcome",
            context={
                "first_name": profile.user.first_name,
                "learner_id": profile.learner_id,
                "uln": profile.uln,
                "login_url": f"{settings.FRONTEND_URL}/test-centre",
            },
        )
        return APIResponse.ok(message="Welcome email re-sent")


_GenerateUlnEnvelope = inline_serializer(
    name="GenerateUlnEnvelope",
    fields={
        "success": drf_serializers.BooleanField(default=True),
        "message": drf_serializers.CharField(),
        "data": inline_serializer(
            name="GenerateUlnData",
            fields={"uln": drf_serializers.RegexField(r"^\d{10}$")},
        ),
    },
)


@extend_schema(
    tags=["Learners"],
    summary="Generate a fresh, DB-unique 10-digit ULN",
    responses={200: _GenerateUlnEnvelope, **DEFAULT_ERROR_RESPONSES},
)
class GenerateUlnView(APIView):
    """
    Returns a unique 10-digit ULN suggestion. Nothing persisted —
    the frontend uses this to prefill the register-learner modal.
    Uniqueness is enforced again on POST in case the admin overrides.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        for _ in range(10):
            candidate = generate_uln()
            if not LearnerProfile.objects.filter(uln=candidate).exists():
                return APIResponse.ok(data={"uln": candidate})
        return APIResponse.fail(
            message="Could not allocate a unique ULN. Try again.",
            errors={"uln": ["allocation failed"]},
            status=503,
        )


@extend_schema(tags=["Learners"], responses={200: envelope_detail(LearnerSerializer), **DEFAULT_ERROR_RESPONSES})
class LearnerByUlnView(generics.RetrieveAPIView):
    """Invigilator ID-verification step."""
    serializer_class = LearnerSerializer
    permission_classes = [IsAdminOrReadOnlyStaff]
    lookup_field = "uln"
    queryset = LearnerProfile.objects.select_related("user").prefetch_related("enrollments__qualification")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return APIResponse.ok(data=self.get_serializer(instance).data)


# ─────────────────────────────────────────────────────────────
# Enrollments
# ─────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=["Enrollments"], responses={200: envelope_array(EnrollmentSerializer, many=True), **DEFAULT_ERROR_RESPONSES}),
    retrieve=extend_schema(tags=["Enrollments"], responses={200: envelope_detail(EnrollmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    create=extend_schema(tags=["Enrollments"], request=CreateEnrollmentSerializer, responses={201: envelope_detail(EnrollmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    partial_update=extend_schema(tags=["Enrollments"], responses={200: envelope_detail(EnrollmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    destroy=extend_schema(tags=["Enrollments"], responses={204: None, **DEFAULT_ERROR_RESPONSES}),
)
class EnrollmentViewSet(viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related("learner__user", "qualification")
    permission_classes = [IsAdmin]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_serializer_class(self):
        if self.action == "create":
            return CreateEnrollmentSerializer
        return EnrollmentSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        learner_id = request.query_params.get("learnerId")
        if learner_id:
            qs = qs.filter(learner__user_id=learner_id)
        return APIResponse.ok(data=EnrollmentSerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = CreateEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = serializer.save()
        return APIResponse.ok(
            data=EnrollmentSerializer(enrollment).data,
            message="Enrollment created",
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Enrollments"], responses={200: envelope_array(EnrollmentSerializer, many=True), **DEFAULT_ERROR_RESPONSES})
class MyEnrollmentsView(generics.ListAPIView):
    """GET /api/me/enrollments/ — used by LearnerDashboard.tsx"""
    serializer_class = EnrollmentSerializer
    permission_classes = [IsSelfLearner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Enrollment.objects.none()
        return Enrollment.objects.filter(
            learner__user=self.request.user,
        ).select_related("qualification").order_by("-enrolled_at")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return APIResponse.ok(data=self.get_serializer(qs, many=True).data)


# ─────────────────────────────────────────────────────────────
# Reasonable Adjustments
# ─────────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(tags=["Reasonable Adjustments"], responses={200: envelope_array(ReasonableAdjustmentSerializer, many=True), **DEFAULT_ERROR_RESPONSES}),
    retrieve=extend_schema(tags=["Reasonable Adjustments"], responses={200: envelope_detail(ReasonableAdjustmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    create=extend_schema(tags=["Reasonable Adjustments"], request=CreateReasonableAdjustmentSerializer, responses={201: envelope_detail(ReasonableAdjustmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    partial_update=extend_schema(tags=["Reasonable Adjustments"], responses={200: envelope_detail(ReasonableAdjustmentSerializer), **DEFAULT_ERROR_RESPONSES}),
    destroy=extend_schema(tags=["Reasonable Adjustments"], responses={204: None, **DEFAULT_ERROR_RESPONSES}),
)
class ReasonableAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = ReasonableAdjustment.objects.select_related("learner__user")
    permission_classes = [IsAdmin]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_serializer_class(self):
        if self.action == "create":
            return CreateReasonableAdjustmentSerializer
        return ReasonableAdjustmentSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        learner_id = request.query_params.get("learnerId")
        if learner_id:
            qs = qs.filter(learner__user_id=learner_id)
        return APIResponse.ok(data=ReasonableAdjustmentSerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = CreateReasonableAdjustmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        ra = serializer.save()
        return APIResponse.ok(
            data=ReasonableAdjustmentSerializer(ra).data,
            message="Reasonable adjustment recorded",
            status=status.HTTP_201_CREATED,
        )
