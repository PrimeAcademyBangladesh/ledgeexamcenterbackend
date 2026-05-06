"""
core/responses.py
Centralised API response helpers.

Every endpoint returns one of these two shapes:

    {"success": true,  "message": "...", "data":   {...}}
    {"success": false, "message": "...", "errors": {...}}

Use APIResponse.ok() / APIResponse.fail() inside ad-hoc views.
ViewSets get the same shape for free via core.renderers.EnvelopeJSONRenderer.
"""
from __future__ import annotations

from typing import Any, Mapping

from rest_framework import status as http_status
from rest_framework.response import Response


_DEFAULT_OK_MESSAGES = {
    "list": "Records retrieved successfully.",
    "retrieve": "Record retrieved successfully.",
    "create": "Record created successfully.",
    "update": "Record updated successfully.",
    "partial_update": "Record updated successfully.",
    "destroy": "Record deleted successfully.",
}


def default_success_message(action: str | None, model_name: str | None = None) -> str:
    base = _DEFAULT_OK_MESSAGES.get(action or "", "Operation completed successfully.")
    if not model_name:
        return base
    return base.replace("Record", model_name).replace("Records", f"{model_name} list")


class APIResponse:
    """Tiny façade over DRF's Response with the project envelope."""

    @staticmethod
    def ok(
        data: Any = None,
        message: str = "Operation completed successfully.",
        status: int = http_status.HTTP_200_OK,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return Response(
            {"success": True, "message": message, "data": data if data is not None else {}},
            status=status,
            headers=dict(headers) if headers else None,
        )

    @staticmethod
    def fail(
        message: str = "Request failed.",
        errors: Any = None,
        status: int = http_status.HTTP_400_BAD_REQUEST,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return Response(
            {"success": False, "message": message, "errors": errors if errors is not None else {}},
            status=status,
            headers=dict(headers) if headers else None,
        )
