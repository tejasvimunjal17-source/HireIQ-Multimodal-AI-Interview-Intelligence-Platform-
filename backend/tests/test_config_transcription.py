"""Day 3 settings validation (real code)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x" * 48}


def make(monkeypatch, **env):
    for key in ("TRANSCRIPTION_PROVIDER", "OPENAI_API_KEY", "ENVIRONMENT", "TRANSCRIPTION_LANGUAGE",
                "TRANSCRIPTION_MAX_RETRIES", "AUDIO_MAX_DURATION_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_defaults_are_safe(monkeypatch):
    s = make(monkeypatch)
    assert s.transcription_provider == "mock" and s.transcription_language is None
    assert s.transcription_max_retries == 3 and s.audio_max_duration_seconds == 600


def test_mock_provider_is_refused_in_production(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, ENVIRONMENT="production", TRANSCRIPTION_PROVIDER="mock")


def test_openai_provider_needs_a_server_side_key(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, TRANSCRIPTION_PROVIDER="openai")
    s = make(monkeypatch, TRANSCRIPTION_PROVIDER="openai", OPENAI_API_KEY="sk-test-123")
    assert s.transcription_provider == "openai" and "sk-test-123" not in repr(s)


def test_production_with_a_real_provider_is_accepted(monkeypatch):
    assert make(monkeypatch, ENVIRONMENT="production", TRANSCRIPTION_PROVIDER="local").environment == "production"


def test_unknown_provider_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, TRANSCRIPTION_PROVIDER="whisperx")


def test_blank_language_means_auto_detect(monkeypatch):
    assert make(monkeypatch, TRANSCRIPTION_LANGUAGE="  ").transcription_language is None
    assert make(monkeypatch, TRANSCRIPTION_LANGUAGE="de").transcription_language == "de"


@pytest.mark.parametrize("name, value", [("TRANSCRIPTION_MAX_RETRIES", "99"), ("AUDIO_MAX_DURATION_SECONDS", "1")])
def test_limits_are_bounded(monkeypatch, name, value):
    with pytest.raises(ValidationError):
        make(monkeypatch, **{name: value})
