from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, parsers, status
from rest_framework.permissions import AllowAny

from core.permission import IsAdmin
from core.responses import APIResponse
from core.schemas import DEFAULT_ERROR_RESPONSES, envelope_detail

from .models import SystemSettings
from .serializers import BrandMiniSerializer, SystemSettingsSerializer


@extend_schema_view(
    get=extend_schema(
        tags=["System Settings"],
        summary="Retrieve system settings",
        responses={
            200: envelope_detail(
                SystemSettingsSerializer,
                message_example="System settings retrieved successfully.",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
    patch=extend_schema(
        tags=["System Settings"],
        summary="Update system settings",
        request=SystemSettingsSerializer,
        responses={
            200: envelope_detail(
                SystemSettingsSerializer,
                message_example="System settings updated successfully.",
            ),
            **DEFAULT_ERROR_RESPONSES,
        },
    ),
)
class SystemSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = SystemSettingsSerializer
    permission_classes = [IsAdmin]
    parser_classes = [parsers.JSONParser, parsers.MultiPartParser, parsers.FormParser]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return SystemSettings.load()

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return APIResponse.ok(
            data=serializer.data,
            message="System settings retrieved successfully.",
        )

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.save()
        return APIResponse.ok(
            data=self.get_serializer(settings_obj).data,
            message="System settings updated successfully.",
            status=status.HTTP_200_OK,
        )


class BrandMiniView(generics.RetrieveAPIView):
    serializer_class = BrandMiniSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return SystemSettings.load()