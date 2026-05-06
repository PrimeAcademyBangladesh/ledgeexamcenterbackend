"""
core/mixins.py
Reusable view/viewset/serializer mixins.
"""
from __future__ import annotations

from rest_framework import status as http_status
from rest_framework.response import Response


# ────────────────────────────────────────────────────────────
#  Per-action serializer selection
# ────────────────────────────────────────────────────────────
class SerializerByActionMixin:
    """
    Map serializer per DRF action without a get_serializer_class() override.

    class FooViewSet(SerializerByActionMixin, ModelViewSet):
        serializer_class = FooDetailSerializer       # default
        serializer_action_classes = {
            "list":           FooListSerializer,
            "create":         FooWriteSerializer,
            "update":         FooWriteSerializer,
            "partial_update": FooWriteSerializer,
        }
    """
    serializer_action_classes: dict = {}

    def get_serializer_class(self):
        return self.serializer_action_classes.get(self.action, super().get_serializer_class())


# ────────────────────────────────────────────────────────────
#  Per-action queryset selection (avoids duplicate evaluations)
# ────────────────────────────────────────────────────────────
class QuerysetByActionMixin:
    """
    Map a queryset *factory* per action so retrieve/list don't reuse the
    same heavy prefetches. Each value must be a callable taking `self`.

    queryset_action_factories = {
        "list":     lambda v: selectors.qualification_list_qs(v.request.user),
        "retrieve": lambda v: selectors.qualification_detail_qs(),
    }
    """
    queryset_action_factories: dict = {}

    def get_queryset(self):
        factory = self.queryset_action_factories.get(self.action)
        if factory is not None:
            return factory(self)
        return super().get_queryset()


# ────────────────────────────────────────────────────────────
#  Soft-delete support
# ────────────────────────────────────────────────────────────
class SoftDeleteMixin:
    """
    Replaces destroy() with a soft-delete strategy.

    Override `soft_delete(instance)` on the viewset/service. Default sets
    `status="withdrawn"` and a timestamp on `withdrawn_at` if those exist.
    """
    soft_delete_status_field = "status"
    soft_delete_status_value = "withdrawn"
    soft_delete_timestamp_field = "withdrawn_at"

    def perform_destroy(self, instance):
        from django.utils import timezone
        update_fields = []
        if hasattr(instance, self.soft_delete_status_field):
            setattr(instance, self.soft_delete_status_field, self.soft_delete_status_value)
            update_fields.append(self.soft_delete_status_field)
        if hasattr(instance, self.soft_delete_timestamp_field):
            setattr(instance, self.soft_delete_timestamp_field, timezone.now().date())
            update_fields.append(self.soft_delete_timestamp_field)
        if hasattr(instance, "updated_at"):
            update_fields.append("updated_at")
        instance.save(update_fields=update_fields or None)


# ────────────────────────────────────────────────────────────
#  Envelope-aware response helpers
# ────────────────────────────────────────────────────────────
class EnvelopeResponseMixin:
    """
    Lets a view set a custom message on the wrapped response without
    importing APIResponse. Use sparingly — most actions get an automatic
    message from the renderer.
    """
    def respond(self, data=None, message: str | None = None, status: int = http_status.HTTP_200_OK, headers=None):
        response = Response(data if data is not None else {}, status=status, headers=headers)
        if message:
            response.message = message
        return response


# ────────────────────────────────────────────────────────────
#  Audit logging (optional)
# ────────────────────────────────────────────────────────────
class AuditLogMixin:
    """
    Records create/update/delete to apps.audit.AuditLog when present.
    No-op if the audit app isn't installed.
    """
    audit_action_map = {
        "create": "create",
        "update": "update",
        "partial_update": "update",
        "destroy": "delete",
    }

    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit("create", instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit("update", instance)

    def perform_destroy(self, instance):
        self._audit("delete", instance)
        super().perform_destroy(instance) if hasattr(super(), "perform_destroy") else instance.delete()

    def _audit(self, action: str, instance) -> None:
        try:
            from apps.audit.models import AuditLog  # type: ignore
        except Exception:
            return
        try:
            AuditLog.objects.create(
                actor=self.request.user,
                action=action,
                model=instance.__class__.__name__,
                object_id=str(instance.pk),
                payload=getattr(self.request, "data", None),
            )
        except Exception:
            # Audit must never break the user-facing request.
            pass
