"""REAL OpenAI Whisper API call. Skipped unless RUN_REAL_WHISPER=1 and OPENAI_API_KEY are set
(see .github/workflows/real-whisper.yml). It costs a tiny amount of money.

It proves the request/response path works with the real service. A generated tone is NOT speech, so the
returned text may be empty: transcription ACCURACY (word error rate) needs a real recording (Day 10)."""

import os

import pytest

from app.core.config import get_settings
from app.services.transcription.factory import get_provider
from tests.helpers_audio import wav_bytes

pytestmark = [
    pytest.mark.real_api,
    pytest.mark.skipif(
        os.environ.get("RUN_REAL_WHISPER") != "1" or not os.environ.get("OPENAI_API_KEY"),
        reason="set RUN_REAL_WHISPER=1 and OPENAI_API_KEY to call the real OpenAI API",
    ),
]


def test_real_openai_whisper_request_succeeds(tmp_path):
    settings = get_settings()
    assert settings.transcription_provider == "openai"
    path = tmp_path / "tone.wav"
    path.write_bytes(wav_bytes(2.0, 16000, 1, amplitude=9000))
    result = get_provider(settings).transcribe(path)
    assert result.provider == "openai" and isinstance(result.text, str)
