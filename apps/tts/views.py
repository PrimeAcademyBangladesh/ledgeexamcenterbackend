"""
apps/tts/views.py

POST /api/tts/speak/
  - Accepts visible exam question text and returns a WAV audio file.
  - Requires authentication; any platform role (learner, invigilator, admin)
    may call this endpoint.
  - Throttled per-user via the "tts" scope defined in settings.

Why direct HttpResponse (not a temp URL)?
  Returning audio bytes in the HTTP body avoids exposing a file URL that
  could be scraped, cached by intermediaries, or hit without auth. The
  response is private (Cache-Control: private) and streamed in one shot —
  WAV files for 1500 chars of text are typically 200–600 KB, well within
  a single response payload.
"""
from __future__ import annotations

import logging

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permission import ALL_ROLES, _has_role
from core.responses import APIResponse

from .serializers import TTSRequestSerializer
from .service import TTSError, synthesize

logger = logging.getLogger("tts")


# ── Session-ownership hook ────────────────────────────────────────────────────

def _can_use_tts(request) -> bool:
    """
    Gate: any authenticated user with a recognised platform role may call
    this endpoint. The frontend is trusted to send only text the learner
    can already see on screen (i.e. question text, not answers).

    To add session-ownership enforcement in future, extend this function:
        from apps.exams.models import ExamSession
        session_id = request.data.get("sessionId")
        if session_id:
            session = ExamSession.objects.filter(
                id=session_id, learner=request.user
            ).exists()
            return session
    """
    return _has_role(request, *ALL_ROLES)


# ── View ──────────────────────────────────────────────────────────────────────

class TTSSpeakView(APIView):
    """
    Convert visible exam text to speech and return a WAV file.
    Throttled at settings.DEFAULT_THROTTLE_RATES["tts"] per authenticated user.
    """
    permission_classes = [IsAuthenticated]
    throttle_scope = "tts"   # pairs with ScopedRateThrottle in DEFAULT_THROTTLE_CLASSES

    @extend_schema(
        tags=["TTS"],
        summary="Synthesise exam text to speech",
        request=TTSRequestSerializer,
        responses={
            200: OpenApiResponse(description="audio/wav file"),
            400: OpenApiResponse(description="Validation error (empty text, bad voice, unsupported format)"),
            401: OpenApiResponse(description="Not authenticated"),
            403: OpenApiResponse(description="Role not permitted"),
            503: OpenApiResponse(description="TTS engine unavailable or timed out"),
        },
    )
    def post(self, request):
        if not _can_use_tts(request):
            return APIResponse.fail(
                message="You do not have permission to use text-to-speech.",
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TTSRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.fail(
                message="Invalid TTS request.",
                errors=serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        text: str = serializer.validated_data["text"]
        voice: str = serializer.validated_data["voice"]

        logger.info(
            "TTS request  user=%s role=%s voice=%s text_len=%d",
            request.user.id,
            getattr(request.user, "role", "unknown"),
            voice,
            len(text),
        )

        try:
            audio_bytes = synthesize(text, voice)
        except TTSError as exc:
            # TTSError carries its own status_code (503) and a human message.
            return APIResponse.fail(
                message=str(exc.detail),
                status=exc.status_code,
            )
        except Exception:
            logger.exception("Unexpected error during TTS for user=%s", request.user.id)
            return APIResponse.fail(
                message="An unexpected error occurred during speech synthesis.",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = HttpResponse(audio_bytes, content_type="audio/wav")
        response["Content-Disposition"] = 'attachment; filename="speech.wav"'
        response["Content-Length"] = str(len(audio_bytes))
        # Private so CDN/proxy caches do not store learner exam audio.
        response["Cache-Control"] = "private, max-age=3600"
        return response
