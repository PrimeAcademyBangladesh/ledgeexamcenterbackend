"""
Invigilators app — viewsets and endpoints.

Endpoints
---------
GET    /api/invigilators/                 list (admin or invigilator-readonly)
POST   /api/invigilators/                 register new invigilator (admin)
GET    /api/invigilators/{id}/            retrieve
PATCH  /api/invigilators/{id}/            update (admin)
DELETE /api/invigilators/{id}/            soft-disable (admin)  -> sets is_active=False
POST   /api/invigilators/{id}/activate/   re-enable (admin)
POST   /api/invigilators/{id}/deactivate/ disable (admin)
POST   /api/invigilators/{id}/resend-welcome/   trigger welcome email (admin)
GET    /api/invigilators/summary/         dashboard counters (total / active / upcoming sessions)
GET    /api/invigilators/by-code/{code}/  lookup by provider_code

GET    /api/invigilators/me/sessions/     sessions assigned to the logged-in invigilator
GET    /api/invigilators/me/availability/ availability slots for current user
POST   /api/invigilators/me/availability/ create a slot
PATCH  /api/invigilators/me/availability/{slot_id}/ update a slot
DELETE /api/invigilators/me/availability/{slot_id}/ delete a slot

GET    /api/invigilators/{id}/availability/ availability slots for an invigilator (admin)
POST   /api/invigilators/{id}/availability/ create a slot for an invigilator (admin)
PATCH  /api/invigilators/{id}/availability/{slot_id}/ update a slot (admin)
DELETE /api/invigilators/{id}/availability/{slot_id}/ delete a slot (admin)

GET    /api/provider-centres/             list of provider centres
POST   /api/provider-centres/             create (admin)
GET/PATCH/DELETE /api/provider-centres/{id}/
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from apps.exams.serializers import ExamSessionSerializer
from apps.users.models import Role, StaffProfile
from core.email import build_set_password_url, send_email
from core.responses import APIResponse
from core.schemas import DEFAULT_ERROR_RESPONSES, EmptyEnvelope, envelope_action, envelope_array, envelope_detail, envelope_list

from .filters import InvigilatorFilter, ProviderCentreFilter
from .models import (
    InvigilatorAvailability,
    InvigilatorProviderLink,
    ProviderCentre,
)
from .permissions import IsAdmin, IsAdminOrInvigilatorReadOnly, IsSelfOrAdmin
from .serializers import (
    AvailabilitySerializer,
    InvigilatorDropDownSerializer,
    InvigilatorSerializer,
    ProviderCentreSerializer,
    RegisterInvigilatorSerializer,
    UpdateInvigilatorSerializer,
)
from apps.exams.models import ExamSession

User = get_user_model()


# OpenAPI shape for the list response: paginated envelope + summary block.
_InvigilatorSummary = inline_serializer(
    name="InvigilatorListSummary",
    fields={
        "totalInvigilators": drf_serializers.IntegerField(),
        "activeInvigilators": drf_serializers.IntegerField(),
        "inactiveInvigilators": drf_serializers.IntegerField(),
        "upcomingSessions": drf_serializers.IntegerField(),
    },
)
_InvigilatorListPage = inline_serializer(
    name="InvigilatorListPage",
    fields={
        "count": drf_serializers.IntegerField(),
        "next": drf_serializers.URLField(allow_null=True, required=False),
        "previous": drf_serializers.URLField(allow_null=True, required=False),
        "summary": _InvigilatorSummary,
        "results": InvigilatorSerializer(many=True),
    },
)
_InvigilatorListEnvelope = inline_serializer(
    name="InvigilatorListEnvelope",
    fields={
        "success": drf_serializers.BooleanField(default=True),
        "message": drf_serializers.CharField(),
        "data": _InvigilatorListPage,
    },
)


# ---------------------------------------------------------------------------
# /api/invigilators/
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["Invigilator"], responses={200: _InvigilatorListEnvelope, **DEFAULT_ERROR_RESPONSES}),
    retrieve=extend_schema(tags=["Invigilator"], responses={200: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES}),
    create=extend_schema(tags=["Invigilator"], request=RegisterInvigilatorSerializer, responses={201: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES}),
    partial_update=extend_schema(tags=["Invigilator"], request=UpdateInvigilatorSerializer, responses={200: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES}),
    destroy=extend_schema(tags=["Invigilator"], responses={204: None, **DEFAULT_ERROR_RESPONSES}),
    activate=extend_schema(tags=["Invigilator"], responses={200: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES}),
    deactivate=extend_schema(tags=["Invigilator"], responses={200: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES}),
    resend_welcome=extend_schema(
        tags=["Invigilator"],
        responses={
            200: envelope_action({"detail": drf_serializers.CharField()}, name="InvigilatorWelcomeQueued"),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
    summary=extend_schema(
        tags=["Invigilator"],
        responses={
            200: envelope_action(
                {
                    "total_invigilators": drf_serializers.IntegerField(),
                    "active": drf_serializers.IntegerField(),
                    "inactive": drf_serializers.IntegerField(),
                    "upcoming_sessions": drf_serializers.IntegerField(),
                },
                name="InvigilatorSummary",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
)
class InvigilatorViewSet(viewsets.ModelViewSet):
    """CRUD for invigilator users."""
    queryset = (
        User.objects.filter(role=Role.INVIGILATOR)
        .select_related("staff_profile")
        .order_by("-date_joined", "-id")
    )
    permission_classes = [IsAuthenticated, IsAdminOrInvigilatorReadOnly]
    filter_backends = [DjangoFilterBackend]
    filterset_class = InvigilatorFilter
    lookup_field = "pk"

    # ----- serializer routing -----
    def get_serializer_class(self):
        if self.action == "create":
            return RegisterInvigilatorSerializer
        if self.action in ("update", "partial_update"):
            return UpdateInvigilatorSerializer
        return InvigilatorSerializer

    def _ensure_availability_access(self, request, target_user):
        if request.user.role == Role.ADMIN:
            return None
        if request.user.role == Role.INVIGILATOR and request.user.id == target_user.id:
            return None
        return APIResponse.fail(
            message="Forbidden",
            errors={"detail": ["You do not have permission to manage this invigilator's availability."]},
            status=status.HTTP_403_FORBIDDEN,
        )

    def _get_availability_slot(self, target_user, slot_id):
        return get_object_or_404(
            InvigilatorAvailability.objects.filter(user=target_user),
            pk=slot_id,
        )

    # ----- list with summary block -----
    def _build_summary(self):
        """Aggregate counters surfaced alongside the paginated results."""
        agg = User.objects.filter(role=Role.INVIGILATOR).aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
        )
        total = agg["total"] or 0
        active = agg["active"] or 0
        upcoming = 0
        try:
            upcoming = ExamSession.objects.filter(
                status="scheduled",
                scheduled_date__gte=timezone.localdate(),
            ).count()
        except ImportError:
            pass
        return {
            "totalInvigilators": total,
            "activeInvigilators": active,
            "inactiveInvigilators": total - active,
            "upcomingSessions": upcoming,
        }

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary = self._build_summary()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            # Inject summary as a sibling of count/next/previous/results.
            response.data = {
                "count": response.data.get("count"),
                "next": response.data.get("next"),
                "previous": response.data.get("previous"),
                "summary": summary,
                "results": response.data.get("results", []),
            }
            return response
        serializer = self.get_serializer(queryset, many=True)
        return APIResponse.ok(data={"summary": summary, "results": serializer.data})

    # ----- soft delete -----
    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ----- custom actions -----
    @action(detail=True, methods=["post"], url_path="activate", permission_classes=[IsAuthenticated, IsAdmin])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        return APIResponse.ok(data=InvigilatorSerializer(user).data, message="Invigilator activated.")

    @action(detail=True, methods=["post"], url_path="deactivate", permission_classes=[IsAuthenticated, IsAdmin])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        return APIResponse.ok(data=InvigilatorSerializer(user).data, message="Invigilator deactivated.")

    @action(detail=True, methods=["post"], url_path="resend-welcome", permission_classes=[IsAuthenticated, IsAdmin])
    def resend_welcome(self, request, pk=None):
        user = self.get_object()
        send_email(
            subject="Welcome to Lead Edge Exam Centre",
            to_email=user.email,
            template_name="invigilator_welcome",
            context={
                "first_name": user.first_name,
                "username": user.email,
                "login_url": f"{settings.FRONTEND_URL}/test-centre",
                "set_password_url": build_set_password_url(user),
            },
        )
        return APIResponse.ok(message=f"Welcome email re-sent to {user.email}")

    # ----- /summary/ -----
    @action(detail=False, methods=["get"], url_path="summary",
            permission_classes=[IsAuthenticated, IsAdminOrInvigilatorReadOnly])
    def summary(self, request):
        """Dashboard counters: total invigilators, active count, and upcoming sessions."""
        agg = User.objects.filter(role=Role.INVIGILATOR).aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
        )
        total = agg["total"] or 0
        active = agg["active"] or 0

        upcoming = 0
        try:
            from apps.exams.models import ExamSession
            upcoming = ExamSession.objects.filter(
                status="scheduled",
                scheduled_date__gte=timezone.localdate(),
            ).count()
        except ImportError:
            pass

        return APIResponse.ok(data={
            "total_invigilators": total,
            "active": active,
            "inactive": total - active,
            "upcoming_sessions": upcoming,
        })

    # ----- /me/sessions/ -----
    @extend_schema(tags=["Invigilator"], responses={200: envelope_array(ExamSessionSerializer, many=True), **DEFAULT_ERROR_RESPONSES})
    @action(detail=False, methods=["get"], url_path="me/sessions",
            permission_classes=[IsAuthenticated])
    def my_sessions(self, request):
        """Return ExamSessions assigned to the logged-in invigilator."""
        if request.user.role != Role.INVIGILATOR:
            return APIResponse.fail(
                message="Forbidden",
                errors={"detail": ["Only invigilators can call this endpoint."]},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            from apps.exams.models import ExamSession
            from apps.exams.serializers import ExamSessionSerializer
        except ImportError:
            return APIResponse.ok(data=[])

        sessions = (ExamSession.objects
                    .filter(invigilator=request.user)
                    .select_related("learner", "exam_config", "exam_config__qualification")
                    .order_by("scheduled_date", "scheduled_time"))
        return APIResponse.ok(data=ExamSessionSerializer(sessions, many=True).data)

    # ----- /me/availability/ -----
    @extend_schema(tags=["Invigilator"], responses={200: envelope_array(AvailabilitySerializer, many=True), 201: envelope_detail(AvailabilitySerializer), **DEFAULT_ERROR_RESPONSES})
    @action(detail=False, methods=["get", "post"], url_path="me/availability",
            permission_classes=[IsAuthenticated])
    def my_availability(self, request):
        if request.user.role != Role.INVIGILATOR:
            return APIResponse.fail(
                message="Forbidden",
                errors={"detail": ["Only invigilators can manage availability."]},
                status=status.HTTP_403_FORBIDDEN,
            )
        if request.method == "GET":
            slots = InvigilatorAvailability.objects.filter(user=request.user, is_active=True)
            return APIResponse.ok(
                data=AvailabilitySerializer(slots, many=True).data,
                message="Availability retrieved.",
            )
        # POST
        ser = AvailabilitySerializer(
            data=request.data,
            context={"availability_user": request.user},
        )
        ser.is_valid(raise_exception=True)
        slot = ser.save(user=request.user)
        return APIResponse.ok(
            data=AvailabilitySerializer(slot).data,
            message="Availability slot created.",
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["Invigilator"], responses={200: envelope_array(AvailabilitySerializer, many=True), 201: envelope_detail(AvailabilitySerializer), **DEFAULT_ERROR_RESPONSES})
    @action(detail=True, methods=["get", "post"], url_path="availability",
            permission_classes=[IsAuthenticated])
    def availability(self, request, pk=None):
        target_user = self.get_object()
        denied = self._ensure_availability_access(request, target_user)
        if denied:
            return denied

        if request.method == "GET":
            slots = InvigilatorAvailability.objects.filter(user=target_user, is_active=True)
            return APIResponse.ok(
                data=AvailabilitySerializer(slots, many=True).data,
                message="Availability retrieved.",
            )

        serializer = AvailabilitySerializer(
            data=request.data,
            context={"availability_user": target_user},
        )
        serializer.is_valid(raise_exception=True)
        slot = serializer.save(user=target_user)
        return APIResponse.ok(
            data=AvailabilitySerializer(slot).data,
            message="Availability slot created.",
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=["Invigilator"], responses={200: envelope_detail(AvailabilitySerializer), 204: EmptyEnvelope, **DEFAULT_ERROR_RESPONSES})
    @action(
        detail=False,
        methods=["patch", "delete"],
        url_path=r"me/availability/(?P<slot_id>[^/.]+)",
        permission_classes=[IsAuthenticated],
    )
    def my_availability_slot(self, request, slot_id=None):
        if request.user.role != Role.INVIGILATOR:
            return APIResponse.fail(
                message="Forbidden",
                errors={"detail": ["Only invigilators can manage availability."]},
                status=status.HTTP_403_FORBIDDEN,
            )

        slot = self._get_availability_slot(request.user, slot_id)
        if request.method == "DELETE":
            slot.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = AvailabilitySerializer(
            slot,
            data=request.data,
            partial=True,
            context={"availability_user": request.user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.ok(
            data=AvailabilitySerializer(slot).data,
            message="Availability slot updated.",
        )

    @extend_schema(tags=["Invigilator"], responses={200: envelope_detail(AvailabilitySerializer), 204: EmptyEnvelope, **DEFAULT_ERROR_RESPONSES})
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"availability/(?P<slot_id>[^/.]+)",
        permission_classes=[IsAuthenticated],
    )
    def availability_slot(self, request, pk=None, slot_id=None):
        target_user = self.get_object()
        denied = self._ensure_availability_access(request, target_user)
        if denied:
            return denied

        slot = self._get_availability_slot(target_user, slot_id)
        if request.method == "DELETE":
            slot.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = AvailabilitySerializer(
            slot,
            data=request.data,
            partial=True,
            context={"availability_user": target_user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.ok(
            data=AvailabilitySerializer(slot).data,
            message="Availability slot updated.",
        )


@extend_schema(tags=["Invigilator"], responses={200: envelope_array(InvigilatorDropDownSerializer, many=True), **DEFAULT_ERROR_RESPONSES})
class InvigilatorDropDownView(ListAPIView):
    queryset = (
        User.objects.filter(is_active=True, role=Role.INVIGILATOR)
        .prefetch_related(
            Prefetch(
                "provider_links",
                queryset=InvigilatorProviderLink.objects
                    .filter(ended_at__isnull=True)
                    .select_related("provider"),
            )
        )
        .order_by("first_name", "last_name")
    )
    serializer_class = InvigilatorDropDownSerializer
    permission_classes = [IsAuthenticated, IsAdminOrInvigilatorReadOnly]
    pagination_class = None


# ---------------------------------------------------------------------------
# Lookup by provider code (used by Admin "Assign invigilator" picker)
# ---------------------------------------------------------------------------
class InvigilatorByProviderCodeView(APIView):
    """
    Lookup endpoint for provider-code based invigilator assignment.

    Why:
      - Admin scheduling and assignment flows often have a provider code before
        they have the invigilator UUID.
    Where:
      - Frontend "Assign invigilator" pickers can resolve a typed/scanned
        provider code into the canonical invigilator record before session
        creation.
    """
    permission_classes = [IsAuthenticated, IsAdminOrInvigilatorReadOnly]
    serializer_class = InvigilatorSerializer

    @extend_schema(
        tags=["Invigilator"],
        summary="Find an invigilator by provider code",
        responses={200: envelope_detail(InvigilatorSerializer), **DEFAULT_ERROR_RESPONSES},
    )
    def get(self, request, code: str):
        normalized = code.strip().upper()
        qs = (
            User.objects
            .filter(
                role=Role.INVIGILATOR,
                provider_links__provider__code__iexact=normalized,
                provider_links__ended_at__isnull=True,
            )
            .select_related("staff_profile")
            .distinct()
        )
        user = get_object_or_404(qs)
        return APIResponse.ok(data=InvigilatorSerializer(user).data)


# ---------------------------------------------------------------------------
# Provider centres
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["Provider Centre"], responses={200: envelope_list(ProviderCentreSerializer), **DEFAULT_ERROR_RESPONSES}),
    retrieve=extend_schema(tags=["Provider Centre"], responses={200: envelope_detail(ProviderCentreSerializer), **DEFAULT_ERROR_RESPONSES}),
    create=extend_schema(tags=["Provider Centre"], request=ProviderCentreSerializer, responses={201: envelope_detail(ProviderCentreSerializer), **DEFAULT_ERROR_RESPONSES}),
    partial_update=extend_schema(tags=["Provider Centre"], request=ProviderCentreSerializer, responses={200: envelope_detail(ProviderCentreSerializer), **DEFAULT_ERROR_RESPONSES}),
    destroy=extend_schema(tags=["Provider Centre"], responses={204: None, **DEFAULT_ERROR_RESPONSES}),
)
class ProviderCentreViewSet(viewsets.ModelViewSet):
    queryset = ProviderCentre.objects.all().order_by("-created_at", "-id")
    serializer_class = ProviderCentreSerializer
    permission_classes = [IsAuthenticated, IsAdminOrInvigilatorReadOnly]
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProviderCentreFilter

    def destroy(self, request, *args, **kwargs):
        # Soft-deactivate: never hard-delete a centre that may have history.
        provider = self.get_object()
        provider.is_active = False
        provider.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)
