"""
core/renderers.py
Wrap every JSON response in the project envelope:

    {"success": true,  "message": "...", "data":   {...}}
    {"success": false, "message": "...", "errors": {...}}

Views may opt out per-response by setting `response.envelope = False`,
or set their own message via `response.message = "..."`.
The exception handler in core.exceptions.py emits the error envelope directly,
so this renderer only handles success payloads.
"""
from __future__ import annotations

from rest_framework.renderers import JSONRenderer
from rest_framework.status import is_success

from .responses import default_success_message


class EnvelopeJSONRenderer(JSONRenderer):
    """JSON renderer that wraps successful payloads in the project envelope."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        view = renderer_context.get("view")

        # Errors: handled by core.exceptions.envelope_exception_handler — pass through.
        if response is None or not is_success(response.status_code):
            return super().render(data, accepted_media_type, renderer_context)

        # Per-response opt-out (e.g. file downloads).
        if getattr(response, "envelope", True) is False:
            return super().render(data, accepted_media_type, renderer_context)

        # If the view already emitted the envelope (e.g. APIResponse.ok), pass through.
        if isinstance(data, dict) and "success" in data and ("data" in data or "errors" in data):
            return super().render(data, accepted_media_type, renderer_context)

        message = (
            getattr(response, "message", None)
            or default_success_message(
                getattr(view, "action", None),
                getattr(getattr(view, "queryset", None), "model", type("", (), {"__name__": ""})).__name__ or None,
            )
        )

        envelope = {"success": True, "message": message, "data": data if data is not None else {}}
        return super().render(envelope, accepted_media_type, renderer_context)
