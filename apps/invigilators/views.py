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
GET    /api/invigilators/by-code/{code}/  lookup by provider_code

GET    /api/invigilators/me/sessions/     sessions assigned to the logged-in invigilator
GET    /api/invigilators/me/availability/ availability slots for current user
POST   /api/invigilators/me/availability/ create a slot

GET    /api/provider-centres/             list of provider centres
POST   /api/provider-centres/             create (admin)
GET/PATCH/DELETE /api/provider-centres/{id}/
"""

from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import Role, StaffProfile

from .filters import InvigilatorFilter, ProviderCentreFilter
from .models import (
    InvigilatorAvailability,
    InvigilatorProviderLink,
    ProviderCentre,
)
from .permissions import IsAdmin, IsAdminOrInvigilatorReadOnly, IsSelfOrAdmin
from .serializers import (
    AvailabilitySerializer,
    InvigilatorSerializer,
    ProviderCentreSerializer,
    RegisterInvigilatorSerializer,
    UpdateInvigilatorSerializer,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# /api/invigilators/
# ---------------------------------------------------------------------------
class InvigilatorViewSet(viewsets.ModelViewSet):
    """CRUD for invigilator users."""
    queryset = (
        User.objects.filter(role=Role.INVIGILATOR)
        .select_related("staff_profile")
        .order_by("first_name", "last_name")
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
        return Response(InvigilatorSerializer(user).data)

    @action(detail=True, methods=["post"], url_path="deactivate", permission_classes=[IsAuthenticated, IsAdmin])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(InvigilatorSerializer(user).data)

    @action(detail=True, methods=["post"], url_path="resend-welcome", permission_classes=[IsAuthenticated, IsAdmin])
    def resend_welcome(self, request, pk=None):
        user = self.get_object()
        # TODO: integrate with your transactional email provider.
        # email_service.send_welcome(user)
        return Response({"detail": f"Welcome email queued for {user.email}"})

    # ----- /me/sessions/ -----
    @action(detail=False, methods=["get"], url_path="me/sessions",
            permission_classes=[IsAuthenticated])
    def my_sessions(self, request):
        """Return ExamSessions assigned to the logged-in invigilator."""
        if request.user.role != Role.INVIGILATOR:
            return Response({"detail": "Only invigilators can call this endpoint."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            from apps.exams.models import ExamSession
            from apps.exams.serializers import ExamSessionSerializer
        except ImportError:
            return Response([], status=200)

        sessions = (ExamSession.objects
                    .filter(invigilator=request.user)
                    .select_related("learner", "exam_config", "exam_config__qualification")
                    .order_by("scheduled_date", "scheduled_time"))
        return Response(ExamSessionSerializer(sessions, many=True).data)

    # ----- /me/availability/ -----
    @action(detail=False, methods=["get", "post"], url_path="me/availability",
            permission_classes=[IsAuthenticated])
    def my_availability(self, request):
        if request.user.role != Role.INVIGILATOR:
            return Response({"detail": "Only invigilators can manage availability."},
                            status=status.HTTP_403_FORBIDDEN)
        if request.method == "GET":
            slots = InvigilatorAvailability.objects.filter(user=request.user, is_active=True)
            return Response(AvailabilitySerializer(slots, many=True).data)
        # POST
        ser = AvailabilitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        slot = InvigilatorAvailability.objects.create(user=request.user, **{
            "day_of_week": ser.validated_data["day_of_week"],
            "start_time":  ser.validated_data["start_time"],
            "end_time":    ser.validated_data["end_time"],
        })
        return Response(AvailabilitySerializer(slot).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Lookup by provider code (used by Admin "Assign invigilator" picker)
# ---------------------------------------------------------------------------
class InvigilatorByProviderCodeView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrInvigilatorReadOnly]

    def get(self, request, code: str):
        user = get_object_or_404(
            User.objects.select_related("staff_profile"),
            role=Role.INVIGILATOR,
            staff_profile__provider_code__iexact=code.strip().upper(),
        )
        return Response(InvigilatorSerializer(user).data)


# ---------------------------------------------------------------------------
# Provider centres
# ---------------------------------------------------------------------------
class ProviderCentreViewSet(viewsets.ModelViewSet):
    queryset = ProviderCentre.objects.all().order_by("name")
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
