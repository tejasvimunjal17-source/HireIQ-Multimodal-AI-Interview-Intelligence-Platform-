"""Transcription providers.

- OpenAI provider: runs against a REAL local HTTP server that imitates the OpenAI endpoint
  (fake_openai.py). The HTTP code is real; the service is a TEST DOUBLE. This is NOT a test of OpenAI.
- Mock provider: returns placeholder text, no recognition.
- Local provider: tested with a fake `whisper` module (MOCKED).
"""

import sys
import types
import wave

import pytest

from app.services.transcription.base import TranscriptionError
from app.services.transcription.factory import get_provider
from app.services.transcription import local_provider
from app.services.transcription.local_provider import LocalWhisperProvider
from app.services.transcription.mock_provider import MOCK_TEXT, MockProvider
from app.services.transcription.openai_provider import OpenAIWhisperProvider
from tests.fake_openai import FakeOpenAI
from tests.helpers_audio import wav_bytes

KEY = "sk-test-key-DO-NOT-LEAK-0123456789"


@pytest.fixture
def server():
    fake = FakeOpenAI()
    yield fake
    fake.close()


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "prepared.wav"
    path.write_bytes(wav_bytes(1.0, 16000, 1))
    return path


def provider_for(server, **kwargs):
    return OpenAIWhisperProvider(api_key=KEY, base_url=server.url, timeout_seconds=kwargs.pop("timeout_seconds", 5), **kwargs)


# ---------------------------------------------------------------- OpenAI provider (fake server)
def test_success_is_parsed_into_a_result(server, wav_file):
    result = provider_for(server).transcribe(wav_file)
    assert result.text == "Hello world"
    assert result.language == "english"
    assert result.duration_seconds == 2.5
    assert result.segments == [{"start": 0.0, "end": 2.5, "text": "Hello world"}]
    assert result.provider == "openai" and result.model == "whisper-1" and result.has_speech


def test_request_is_built_correctly(server, wav_file):
    provider_for(server).transcribe(wav_file, language="de")
    request = server.requests[0]
    assert request["path"] == "/v1/audio/transcriptions"
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert request["headers"]["Content-Type"].startswith("multipart/form-data")
    body = request["body"]
    for fragment in (b'name="model"', b"whisper-1", b'name="response_format"', b"verbose_json",
                     b'name="language"', b"de", b'name="file"', b".wav", b"RIFF"):
        assert fragment in body


def test_empty_text_means_no_speech(server, wav_file):
    server.queue(body={"text": "  ", "language": "english", "duration": 1.0, "segments": []})
    result = provider_for(server).transcribe(wav_file)
    assert result.text == "" and not result.has_speech


def test_rate_limit_is_retryable_and_reports_retry_after(server, wav_file):
    server.queue(status=429, headers={"Retry-After": "7"}, body={"error": {"message": "slow down"}})
    with pytest.raises(TranscriptionError) as exc:
        provider_for(server).transcribe(wav_file)
    assert (exc.value.code, exc.value.retryable, exc.value.retry_after) == ("rate_limited", True, 7.0)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retryable(server, wav_file, status):
    server.queue(status=status, body={"error": {}})
    with pytest.raises(TranscriptionError) as exc:
        provider_for(server).transcribe(wav_file)
    assert exc.value.code == "provider_error" and exc.value.retryable


@pytest.mark.parametrize("status, code", [(401, "provider_auth"), (403, "provider_auth"), (400, "provider_rejected_audio"), (413, "provider_rejected_audio")])
def test_permanent_errors_are_not_retryable(server, wav_file, status, code):
    server.queue(status=status, body={"error": {"message": "nope"}})
    with pytest.raises(TranscriptionError) as exc:
        provider_for(server).transcribe(wav_file)
    assert exc.value.code == code and exc.value.retryable is False


@pytest.mark.parametrize("step", [{"raw": b"<html>gateway</html>"}, {"body": {"no_text_here": 1}}, {"body": {"text": 123}}])
def test_unreadable_responses_are_retryable(server, wav_file, step):
    server.queue(**step)
    with pytest.raises(TranscriptionError) as exc:
        provider_for(server).transcribe(wav_file)
    assert exc.value.code == "provider_bad_response" and exc.value.retryable


def test_slow_server_times_out(server, wav_file):
    server.queue(delay=2.0)
    with pytest.raises(TranscriptionError) as exc:
        provider_for(server, timeout_seconds=0.5).transcribe(wav_file)
    assert exc.value.code == "provider_timeout" and exc.value.retryable


def test_unreachable_server_is_retryable(wav_file):
    provider = OpenAIWhisperProvider(api_key=KEY, base_url="http://127.0.0.1:1/v1", timeout_seconds=2)
    with pytest.raises(TranscriptionError) as exc:
        provider.transcribe(wav_file)
    assert exc.value.code == "provider_unreachable" and exc.value.retryable


def test_api_key_never_appears_in_errors_or_repr(server, wav_file):
    server.queue(status=401, body={"error": {"message": "bad key"}})
    provider = provider_for(server)
    with pytest.raises(TranscriptionError) as exc:
        provider.transcribe(wav_file)
    assert KEY not in str(exc.value) and KEY not in repr(provider) and KEY not in repr(exc.value)


def test_missing_key_is_a_configuration_error():
    with pytest.raises(TranscriptionError) as exc:
        OpenAIWhisperProvider(api_key="")
    assert exc.value.code == "provider_not_configured" and not exc.value.retryable


# ---------------------------------------------------------------- mock provider
def test_mock_provider_returns_clearly_fake_text(wav_file):
    result = MockProvider().transcribe(wav_file)
    assert result.text == MOCK_TEXT and "MOCK" in result.text
    assert result.provider == "mock" and result.duration_seconds == pytest.approx(1.0, abs=0.01)


def test_mock_provider_survives_a_non_wav_file(tmp_path):
    odd = tmp_path / "x.wav"
    odd.write_bytes(b"not a wav")
    assert MockProvider().transcribe(odd).duration_seconds is None


# ---------------------------------------------------------------- local provider (fake whisper module)
@pytest.fixture(autouse=True)
def _clear_local_model_cache():
    local_provider._MODELS.clear()
    yield
    local_provider._MODELS.clear()


def test_local_provider_without_the_package_reports_it(monkeypatch, wav_file):
    monkeypatch.setitem(sys.modules, "whisper", None)  # makes `import whisper` raise ImportError
    with pytest.raises(TranscriptionError) as exc:
        LocalWhisperProvider("base").transcribe(wav_file)
    assert exc.value.code == "provider_not_installed" and not exc.value.retryable


def test_local_provider_maps_whisper_output(monkeypatch, wav_file):
    class FakeModel:
        def transcribe(self, path, language=None, fp16=True):
            assert fp16 is False
            return {"text": " hi there ", "language": "en",
                    "segments": [{"start": 0.0, "end": 1.2, "text": " hi there "}]}

    fake = types.ModuleType("whisper")
    fake.load_model = lambda name: FakeModel()
    monkeypatch.setitem(sys.modules, "whisper", fake)
    result = LocalWhisperProvider("base").transcribe(wav_file)
    assert (result.text, result.language, result.duration_seconds, result.provider) == ("hi there", "en", 1.2, "local")


# ---------------------------------------------------------------- factory
def make_settings(monkeypatch, **env):
    from app.core.config import Settings

    for key, value in {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x" * 40, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_factory_builds_the_selected_provider(monkeypatch):
    assert isinstance(get_provider(make_settings(monkeypatch, TRANSCRIPTION_PROVIDER="mock")), MockProvider)
    assert isinstance(get_provider(make_settings(monkeypatch, TRANSCRIPTION_PROVIDER="local")), LocalWhisperProvider)
    openai = get_provider(make_settings(monkeypatch, TRANSCRIPTION_PROVIDER="openai", OPENAI_API_KEY=KEY))
    assert isinstance(openai, OpenAIWhisperProvider) and KEY not in repr(openai)
