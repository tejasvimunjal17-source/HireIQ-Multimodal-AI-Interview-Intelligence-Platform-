"""Configuration loading and environment variable handling (real code, no mocks)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

STRONG_SECRET = "x" * 48


def make_settings(monkeypatch, **env):
    for key in ("DATABASE_URL", "SECRET_KEY", "REDIS_URL", "ENVIRONMENT", "LOG_LEVEL",
                "OPENAI_API_KEY", "GEMINI_API_KEY", "CORS_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_required_values_load_and_defaults_apply(monkeypatch):
    s = make_settings(monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc")
    assert s.environment == "development"
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.log_level == "INFO"
    assert s.openai_api_key is None and s.gemini_api_key is None


def test_missing_database_url_is_an_error(monkeypatch):
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, SECRET_KEY="abc")


def test_missing_secret_key_is_an_error(monkeypatch):
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, DATABASE_URL="sqlite://")


def test_environment_variables_override_defaults(monkeypatch):
    s = make_settings(
        monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc",
        REDIS_URL="redis://redis:6379/5", LOG_LEVEL="debug", ENVIRONMENT="test",
    )
    assert s.redis_url == "redis://redis:6379/5"
    assert s.log_level == "DEBUG"
    assert s.environment == "test"


def test_invalid_environment_and_log_level_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc", ENVIRONMENT="staging")
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc", LOG_LEVEL="loud")


def test_cors_origins_are_parsed_from_comma_separated_string(monkeypatch):
    s = make_settings(
        monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc",
        CORS_ORIGINS=" http://a.com , http://b.com ,, ",
    )
    assert s.cors_origins_list == ["http://a.com", "http://b.com"]


def test_empty_api_keys_become_none_and_real_ones_are_hidden(monkeypatch):
    s = make_settings(monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc", OPENAI_API_KEY="", GEMINI_API_KEY="  ")
    assert s.openai_api_key is None and s.gemini_api_key is None

    s = make_settings(monkeypatch, DATABASE_URL="sqlite://", SECRET_KEY="abc", OPENAI_API_KEY="sk-fake-for-test")
    assert s.openai_api_key.get_secret_value() == "sk-fake-for-test"
    assert "sk-fake-for-test" not in repr(s)
    assert "sk-fake-for-test" not in str(s.model_dump())


def test_production_rejects_placeholder_or_short_secret(monkeypatch):
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, DATABASE_URL="sqlite://", ENVIRONMENT="production",
                      SECRET_KEY="change-me-generate-a-long-random-string-padding-xxxxxxxx")
    with pytest.raises(ValidationError):
        make_settings(monkeypatch, DATABASE_URL="sqlite://", ENVIRONMENT="production", SECRET_KEY="short")


def test_production_accepts_strong_secret(monkeypatch):
    s = make_settings(monkeypatch, DATABASE_URL="sqlite://", ENVIRONMENT="production", SECRET_KEY=STRONG_SECRET)
    assert s.environment == "production"


def test_get_settings_is_cached_and_reads_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Custom Name")
    assert get_settings() is get_settings()
    assert get_settings().app_name == "Custom Name"
