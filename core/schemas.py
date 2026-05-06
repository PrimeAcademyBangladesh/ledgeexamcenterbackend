"""
core/schemas.py
drf-spectacular helpers that document the project envelope:

    {"success": true,  "message": "...", "data":   {...}}
    {"success": false, "message": "...", "errors": {...}}

Use envelope_detail() / envelope_list() / envelope_action() to wrap a
serializer (or inline shape) in the correct response schema, then attach
via @extend_schema(responses=...).
"""
from __future__ import annotations

from functools import lru_cache

from drf_spectacular.utils import OpenApiTypes, inline_serializer
from rest_framework import serializers


# ────────────────────────────────────────────────────────────
#  Internal helpers
# ────────────────────────────────────────────────────────────
def _resolve_field(data_serializer):
    """Accept either a Serializer subclass or an already-built field."""
    if isinstance(data_serializer, type) and issubclass(data_serializer, serializers.Serializer):
        return data_serializer()
    return data_serializer


def _name(data_serializer, suffix: str) -> str:
    if isinstance(data_serializer, type):
        return f"{data_serializer.__name__}{suffix}"
    return f"Inline{suffix}"


# ────────────────────────────────────────────────────────────
#  Envelope builders — cached so repeated decorator calls reuse one
#  generated component name (avoids drf-spectacular duplicate-name warnings).
# ────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def _envelope_detail_class(data_serializer_cls):
    """One envelope component per serializer class — message is documentation, not part of the schema identity."""
    return inline_serializer(
        name=f"{data_serializer_cls.__name__}EnvelopeDetail",
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": data_serializer_cls(),
        },
    )


@lru_cache(maxsize=None)
def _envelope_list_class(data_serializer_cls):
    base = data_serializer_cls.__name__
    paginated = inline_serializer(
        name=f"{base}EnvelopeListPage",
        fields={
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True, required=False),
            "previous": serializers.URLField(allow_null=True, required=False),
            "results": data_serializer_cls(many=True),
        },
    )
    return inline_serializer(
        name=f"{base}EnvelopeList",
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(),
            "data": paginated,
        },
    )


def envelope_detail(data_serializer, *, message_example: str = "Operation completed successfully."):
    """Single-object payload — used by retrieve/create/update.
    `message_example` is intentionally not part of the schema identity — one wrapper component per serializer."""
    if isinstance(data_serializer, type):
        return _envelope_detail_class(data_serializer)
    # Already-built field instance (e.g. SomeSerializer(many=True)) — non-cacheable, return inline.
    return inline_serializer(
        name=_name(data_serializer, "EnvelopeDetail"),
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(default=message_example),
            "data": _resolve_field(data_serializer),
        },
    )


def envelope_list(data_serializer, *, message_example: str = "Records retrieved successfully."):
    """Paginated list payload — DRF PageNumberPagination wrapped in the envelope."""
    if isinstance(data_serializer, type):
        return _envelope_list_class(data_serializer)
    name = _name(data_serializer, "EnvelopeList")
    paginated = inline_serializer(
        name=f"{name}Page",
        fields={
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True, required=False),
            "previous": serializers.URLField(allow_null=True, required=False),
            "results": _resolve_field(data_serializer),
        },
    )
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(default=message_example),
            "data": paginated,
        },
    )


def envelope_action(fields: dict, *, name: str, message_example: str = "Operation completed successfully."):
    """
    Custom @action endpoint (no model serializer behind it).
    Pass a dict of {field_name: drf_field} for the data shape.
    """
    return inline_serializer(
        name=f"{name}Envelope",
        fields={
            "success": serializers.BooleanField(default=True),
            "message": serializers.CharField(default=message_example),
            "data": inline_serializer(name=f"{name}Data", fields=fields),
        },
    )


# ────────────────────────────────────────────────────────────
#  Reusable error response schema
# ────────────────────────────────────────────────────────────
ErrorEnvelope = inline_serializer(
    name="ErrorEnvelope",
    fields={
        "success": serializers.BooleanField(default=False),
        "message": serializers.CharField(default="Request failed."),
        "errors": serializers.DictField(child=serializers.ListField(child=serializers.CharField())),
    },
)

DEFAULT_ERROR_RESPONSES = {
    400: ErrorEnvelope,
    401: ErrorEnvelope,
    403: ErrorEnvelope,
    404: ErrorEnvelope,
    409: ErrorEnvelope,
}


# ────────────────────────────────────────────────────────────
#  Empty-data envelope (e.g. 204-style ack with 200 status)
# ────────────────────────────────────────────────────────────
EmptyEnvelope = inline_serializer(
    name="EmptyEnvelope",
    fields={
        "success": serializers.BooleanField(default=True),
        "message": serializers.CharField(default="Operation completed successfully."),
        "data": serializers.DictField(default=dict),
    },
)
