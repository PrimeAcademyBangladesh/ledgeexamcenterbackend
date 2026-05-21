"""
apps/tts/serializers.py
Request validation for the TTS speak endpoint.

Field names are camelCase on the wire; validated_data uses them too
because there is no model to map back to snake_case.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

# Read at import time — safe because Django settings are configured before
# any app code is imported.
_MAX_LEN = getattr(settings, "TTS_MAX_TEXT_LENGTH", 1500)


class TTSRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        min_length=1,
        max_length=_MAX_LEN,
        trim_whitespace=True,
        error_messages={
            "blank":      "text must not be empty.",
            "required":   "text is required.",
            "max_length": f"text exceeds the {_MAX_LEN}-character limit.",
            "min_length": "text must not be empty.",
        },
    )
    # voice is optional; defaults to TTS_DEFAULT_VOICE if omitted.
    voice = serializers.CharField(required=False, allow_blank=False, default=None)
    # format is always "wav" for now; kept in the contract so clients can
    # be updated in future without a breaking change.
    format = serializers.ChoiceField(
        choices=["wav"],
        required=False,
        default="wav",
        error_messages={
            "invalid_choice": "Only 'wav' format is currently supported.",
        },
    )

    def validate_voice(self, value):
        if value is None:
            return settings.TTS_DEFAULT_VOICE

        allowed = set(settings.TTS_VOICES.keys())
        if value not in allowed:
            raise serializers.ValidationError(
                f"Voice '{value}' is not available. "
                f"Choose from: {', '.join(sorted(allowed))}."
            )
        return value

    def validate(self, attrs):
        # Ensure voice is always populated (handles the case where the field
        # defaulted to None before validate_voice ran).
        if not attrs.get("voice"):
            attrs["voice"] = settings.TTS_DEFAULT_VOICE
        return attrs
