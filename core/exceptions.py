"""
core/exceptions.py
Custom DRF exception handler that emits the project error envelope:

    {"success": false, "message": "...", "errors": {...}}

Wired in settings.REST_FRAMEWORK["EXCEPTION_HANDLER"].
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


def _flatten_message(detail) -> str:
    """Collapse DRF detail structures into a single human-readable string."""
    if isinstance(detail, exceptions.ErrorDetail):
        return str(detail)
    if isinstance(detail, list) and detail:
        return _flatten_message(detail[0])
    if isinstance(detail, dict) and detail:
        first_key = next(iter(detail))
        first_val = detail[first_key]
        if first_key == "non_field_errors":
            return _flatten_message(first_val)
        return _flatten_message(first_val)
    return "Request failed."


def _normalise_errors(detail):
    """Always return a dict so frontends can index it consistently."""
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, list):
        return {"non_field_errors": detail}
    return {"detail": [str(detail)]}


def envelope_exception_handler(exc, context):
    # Map Django's ValidationError → DRF's so it gets the same envelope.
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()

    response = drf_default_handler(exc, context)
    if response is None:
        # Unhandled exception — let Django's 500 path take over.
        return None

    detail = response.data
    payload = {
        "success": False,
        "message": _flatten_message(detail),
        "errors": _normalise_errors(detail),
    }
    return Response(payload, status=response.status_code, headers=getattr(response, "headers", None))


# ────────────────────────────────────────────────────────────
#  Domain exceptions — raise these from services/selectors.
# ────────────────────────────────────────────────────────────
class DomainError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Operation could not be completed."
    default_code = "domain_error"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource conflict."
    default_code = "conflict"
