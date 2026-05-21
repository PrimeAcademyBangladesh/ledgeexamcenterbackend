"""
tests/test_tts.py
Full test suite for POST /api/tts/speak/

Piper is never invoked during tests — _piper_synthesize is mocked so the
test suite runs offline with no Piper binary installed.

Fixtures from conftest.py: admin_client, invigilator_client, learner_client,
                            learner2_client, anon_client
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.cache import cache as django_cache

TTS_URL = "/api/tts/speak/"

# Minimal valid WAV bytes (RIFF header stub, 44+ bytes).
# Piper would return a real WAV; we just need non-empty bytes of the right type.
_RIFF_HEADER = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
VALID_WAV = _RIFF_HEADER + b"\x00" * 30  # 46 bytes total


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_tts_cache():
    """
    Wipe the Django cache before and after each test so cache-hit tests
    start clean and don't pollute later tests.
    """
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def mock_piper_ok():
    """Patch _piper_synthesize to return VALID_WAV without invoking Piper."""
    with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV) as m:
        yield m


@pytest.fixture
def mock_piper_fail():
    """Patch _piper_synthesize to raise TTSError (simulates Piper crash)."""
    from apps.tts.service import TTSError
    with patch("apps.tts.service._piper_synthesize", side_effect=TTSError()) as m:
        yield m


@pytest.fixture
def mock_piper_timeout():
    """Patch _piper_synthesize to raise TTSError with a timeout message."""
    from apps.tts.service import TTSError
    with patch(
        "apps.tts.service._piper_synthesize",
        side_effect=TTSError("Speech synthesis timed out. Try a shorter passage."),
    ) as m:
        yield m


# ── Authentication ────────────────────────────────────────────────────────────

class TestTTSAuthentication:
    def test_anonymous_request_is_rejected(self, anon_client):
        resp = anon_client.post(TTS_URL, {"text": "Hello"}, format="json")
        assert resp.status_code == 401

    def test_learner_can_call_endpoint(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Hello world"}, format="json")
        assert resp.status_code == 200

    def test_invigilator_can_call_endpoint(self, invigilator_client, mock_piper_ok, db):
        resp = invigilator_client.post(TTS_URL, {"text": "Hello world"}, format="json")
        assert resp.status_code == 200

    def test_admin_can_call_endpoint(self, admin_client, mock_piper_ok, db):
        resp = admin_client.post(TTS_URL, {"text": "Hello world"}, format="json")
        assert resp.status_code == 200


# ── Validation ────────────────────────────────────────────────────────────────

class TestTTSValidation:
    def test_empty_text_is_rejected(self, learner_client, db):
        resp = learner_client.post(TTS_URL, {"text": ""}, format="json")
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    def test_missing_text_field_is_rejected(self, learner_client, db):
        resp = learner_client.post(TTS_URL, {}, format="json")
        assert resp.status_code == 400

    def test_whitespace_only_text_is_rejected(self, learner_client, db):
        # After trim_whitespace=True, "   " becomes "", which fails min_length=1.
        resp = learner_client.post(TTS_URL, {"text": "   "}, format="json")
        assert resp.status_code == 400

    def test_text_at_max_length_is_accepted(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "a" * 1500}, format="json")
        assert resp.status_code == 200

    def test_text_over_max_length_is_rejected(self, learner_client, db):
        resp = learner_client.post(TTS_URL, {"text": "a" * 1501}, format="json")
        assert resp.status_code == 400
        data = resp.json()
        assert "text" in str(data)

    def test_invalid_voice_is_rejected(self, learner_client, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "voice": "../../etc/passwd"},
            format="json",
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    def test_unknown_voice_name_is_rejected(self, learner_client, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "voice": "google_wavenet_fancy"},
            format="json",
        )
        assert resp.status_code == 400

    def test_unsupported_format_is_rejected(self, learner_client, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "format": "mp3"},
            format="json",
        )
        assert resp.status_code == 400

    def test_wav_format_is_accepted(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "format": "wav"},
            format="json",
        )
        assert resp.status_code == 200

    def test_default_voice_is_used_when_omitted(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Hello"}, format="json")
        assert resp.status_code == 200
        # Piper was called exactly once (not blocked by voice validation).
        mock_piper_ok.assert_called_once()

    def test_valid_voice_name_is_accepted(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "voice": "southern_english_female"},
            format="json",
        )
        assert resp.status_code == 200

    def test_uk_male_voice_is_accepted(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(
            TTS_URL,
            {"text": "Hello", "voice": "uk_male"},
            format="json",
        )
        assert resp.status_code == 200


# ── Successful response shape ──────────────────────────────────────────────────

class TestTTSSuccessResponse:
    def test_response_content_type_is_wav(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Read this question."}, format="json")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "audio/wav"

    def test_content_disposition_names_speech_wav(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Read this question."}, format="json")
        assert "speech.wav" in resp["Content-Disposition"]

    def test_content_length_header_matches_body(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Read this question."}, format="json")
        assert int(resp["Content-Length"]) == len(VALID_WAV)

    def test_response_body_is_the_audio_bytes(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Read this question."}, format="json")
        assert resp.content == VALID_WAV

    def test_cache_control_is_private(self, learner_client, mock_piper_ok, db):
        resp = learner_client.post(TTS_URL, {"text": "Read this question."}, format="json")
        assert "private" in resp["Cache-Control"]


# ── Piper failure scenarios ────────────────────────────────────────────────────

class TestTTSPiperFailures:
    def test_piper_crash_returns_503(self, learner_client, mock_piper_fail, db):
        resp = learner_client.post(TTS_URL, {"text": "Hello"}, format="json")
        assert resp.status_code == 503

    def test_piper_crash_returns_json_envelope(self, learner_client, mock_piper_fail, db):
        resp = learner_client.post(TTS_URL, {"text": "Hello"}, format="json")
        data = resp.json()
        assert data["success"] is False
        assert "message" in data

    def test_piper_timeout_returns_503(self, learner_client, mock_piper_timeout, db):
        resp = learner_client.post(TTS_URL, {"text": "Hello"}, format="json")
        assert resp.status_code == 503

    def test_piper_binary_missing_returns_503(self, learner_client, db):
        """FileNotFoundError inside _piper_synthesize is caught and re-raised as TTSError."""
        from apps.tts.service import TTSError
        with patch(
            "apps.tts.service._piper_synthesize",
            side_effect=TTSError("TTS engine is not available on this server."),
        ):
            resp = learner_client.post(TTS_URL, {"text": "Hello"}, format="json")
        assert resp.status_code == 503
        assert resp.json()["success"] is False


# ── Cache behaviour ───────────────────────────────────────────────────────────

class TestTTSCache:
    def test_second_request_with_same_text_skips_piper(self, learner_client, db):
        """Cache hit: Piper should be called once, not twice."""
        with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV) as mock_piper:
            resp1 = learner_client.post(
                TTS_URL, {"text": "What is the capital of England?"}, format="json"
            )
            assert resp1.status_code == 200
            assert mock_piper.call_count == 1

            resp2 = learner_client.post(
                TTS_URL, {"text": "What is the capital of England?"}, format="json"
            )
            assert resp2.status_code == 200
            # Should still be 1 — cache served the second request.
            assert mock_piper.call_count == 1

    def test_cached_response_body_matches_original(self, learner_client, db):
        with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV):
            resp1 = learner_client.post(TTS_URL, {"text": "Cache body check."}, format="json")
            resp2 = learner_client.post(TTS_URL, {"text": "Cache body check."}, format="json")
        assert resp1.content == resp2.content == VALID_WAV

    def test_different_text_calls_piper_again(self, learner_client, db):
        """Two distinct texts should each invoke Piper once."""
        with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV) as mock_piper:
            learner_client.post(TTS_URL, {"text": "First question text."}, format="json")
            learner_client.post(TTS_URL, {"text": "Second question text."}, format="json")
        assert mock_piper.call_count == 2

    def test_different_voices_same_text_calls_piper_twice(self, learner_client, db):
        """Cache key includes the voice name — different voice → cache miss."""
        with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV) as mock_piper:
            learner_client.post(
                TTS_URL,
                {"text": "Same question.", "voice": "southern_english_female"},
                format="json",
            )
            learner_client.post(
                TTS_URL,
                {"text": "Same question.", "voice": "uk_male"},
                format="json",
            )
        assert mock_piper.call_count == 2


# ── Service unit tests ────────────────────────────────────────────────────────

class TestTTSServiceUnit:
    """
    Direct tests of service.py logic without HTTP overhead.
    These run without db fixture because the service layer has no ORM calls.
    """

    def test_cache_key_is_deterministic(self):
        from apps.tts.service import _cache_key
        k1 = _cache_key("Hello world", "southern_english_female")
        k2 = _cache_key("Hello world", "southern_english_female")
        assert k1 == k2

    def test_cache_key_differs_by_voice(self):
        from apps.tts.service import _cache_key
        k1 = _cache_key("Hello", "southern_english_female")
        k2 = _cache_key("Hello", "uk_male")
        assert k1 != k2

    def test_cache_key_differs_by_text(self):
        from apps.tts.service import _cache_key
        k1 = _cache_key("Question A?", "southern_english_female")
        k2 = _cache_key("Question B?", "southern_english_female")
        assert k1 != k2

    def test_cache_key_has_namespace_prefix(self):
        from apps.tts.service import _cache_key
        key = _cache_key("test", "southern_english_female")
        assert key.startswith("tts:")

    def test_tts_error_has_503_status(self):
        from apps.tts.service import TTSError
        err = TTSError()
        assert err.status_code == 503

    def test_synthesize_returns_cached_bytes_without_piper(self, db):
        from apps.tts.service import synthesize, _cache_key
        key = _cache_key("Cached question.", "southern_english_female")
        django_cache.set(key, VALID_WAV, 60)
        with patch("apps.tts.service._piper_synthesize") as mock_piper:
            result = synthesize("Cached question.", "southern_english_female")
        assert result == VALID_WAV
        mock_piper.assert_not_called()

    def test_synthesize_stores_result_in_cache(self, db):
        from apps.tts.service import synthesize, _cache_key
        with patch("apps.tts.service._piper_synthesize", return_value=VALID_WAV):
            synthesize("Store this.", "southern_english_female")
        key = _cache_key("Store this.", "southern_english_female")
        assert django_cache.get(key) == VALID_WAV
