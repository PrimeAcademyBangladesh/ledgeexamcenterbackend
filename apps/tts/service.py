"""
apps/tts/service.py
Text-to-speech service layer — wraps Piper TTS via subprocess.

All Piper-specific logic is isolated here so the view stays thin and
the engine can be swapped later (Coqui, Google, Azure) by re-implementing
_piper_synthesize() and updating TTS_VOICES in settings.

Public API:
    synthesize(text, voice) -> bytes   # returns WAV audio bytes
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger("tts")


# ── Domain exception ──────────────────────────────────────────────────────────

class TTSError(APIException):
    """
    Raised when Piper fails, times out, or is misconfigured.
    Maps to HTTP 503 so the frontend can distinguish a TTS outage from
    a validation error (400) or auth error (401/403).
    """
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Speech synthesis failed. Please try again."
    default_code = "tts_error"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_key(text: str, voice: str) -> str:
    """Deterministic SHA-256 key — safe for all cache backends."""
    digest = hashlib.sha256(f"{voice}:{text}".encode("utf-8")).hexdigest()
    return f"tts:v1:{digest}"


# ── Piper subprocess ──────────────────────────────────────────────────────────

def _piper_synthesize(text: str, model: str, config: str) -> bytes:
    """
    Invoke the Piper binary and return raw WAV bytes.

    Piper writes a proper WAV file (with RIFF header) when given
    --output_file. We use a NamedTemporaryFile so the header is included
    automatically; raw stdout mode (--output-raw) would require us to
    reconstruct the header manually.

    subprocess.run() is used without shell=True; the voice name is never
    passed to the shell — only validated model/config paths from settings.
    """
    output_path: str | None = None
    try:
        # Create temp file first, close it so Piper can open it on Windows too.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            output_path = tmp.name

        result = subprocess.run(
            [
                settings.TTS_PIPER_BINARY,
                "--model",       model,
                "--config",      config,
                "--output_file", output_path,
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=settings.TTS_PIPER_TIMEOUT,
            # check=False so we can log stderr before raising
        )

        if result.returncode != 0:
            stderr_snippet = result.stderr.decode(errors="replace").strip()[:300]
            logger.error(
                "Piper exited with code %d. stderr: %s",
                result.returncode, stderr_snippet,
            )
            raise TTSError()

        with open(output_path, "rb") as f:
            audio = f.read()

        if len(audio) < 44:
            # WAV header is 44 bytes minimum; anything shorter is corrupt.
            logger.error("Piper produced a truncated WAV (%d bytes)", len(audio))
            raise TTSError()

        return audio

    except FileNotFoundError:
        # Piper binary missing or wrong path in settings.
        logger.error("Piper binary not found at '%s'", settings.TTS_PIPER_BINARY)
        raise TTSError("TTS engine is not available on this server.")

    except subprocess.TimeoutExpired:
        logger.error("Piper timed out after %ss for text_len=%d", settings.TTS_PIPER_TIMEOUT, len(text))
        raise TTSError("Speech synthesis timed out. Try a shorter passage.")

    finally:
        if output_path and os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except OSError:
                pass


# ── Public API ────────────────────────────────────────────────────────────────

def synthesize(text: str, voice: str) -> bytes:
    """
    Return WAV audio bytes for the given text and voice name.

    Results are cached by (voice + text) hash so repeated reads of the
    same exam question skip Piper entirely. Cache lifetime is controlled
    by settings.TTS_CACHE_TIMEOUT (default 1 hour).

    The voice name must already be validated against settings.TTS_VOICES
    by the serializer before this function is called.
    """
    key = _cache_key(text, voice)
    cached = cache.get(key)
    if cached is not None:
        logger.debug("TTS cache hit  voice=%s text_len=%d", voice, len(text))
        return cached

    voice_configs: dict = settings.TTS_VOICES
    voice_cfg = voice_configs.get(voice)
    if not voice_cfg:
        # Serializer should have already rejected unknown voices; this is a
        # hard guard against settings misconfiguration.
        logger.error("Voice '%s' requested but not in TTS_VOICES", voice)
        raise TTSError(f"Voice '{voice}' is not configured on this server.")

    audio = _piper_synthesize(text, voice_cfg["model"], voice_cfg["config"])

    timeout = getattr(settings, "TTS_CACHE_TIMEOUT", 3600)
    cache.set(key, audio, timeout=timeout)
    logger.info(
        "TTS synthesized voice=%s text_len=%d audio_bytes=%d",
        voice, len(text), len(audio),
    )
    return audio
