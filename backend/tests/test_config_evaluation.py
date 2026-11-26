"""Day 4 foundation: evaluation settings, production safety, and packaging consistency (real code)."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from app.core.config import DEFAULT_RUBRICS_DIR, Settings

ROOT = Path(__file__).resolve().parents[2]
needs_repo = pytest.mark.skipif(
    not (ROOT / "docker-compose.yml").exists(),
    reason="repository root files not present (running inside the backend-only Docker image)",
)

BASE = {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x" * 48}
CLEARED = (
    "ENVIRONMENT", "TRANSCRIPTION_PROVIDER", "OPENAI_API_KEY", "GEMINI_API_KEY", "EVALUATION_PROVIDER",
    "EVALUATION_MODEL", "EVALUATION_TIMEOUT_SECONDS", "EVALUATION_MAX_RETRIES",
    "EVALUATION_RETRY_BACKOFF_SECONDS", "RUBRICS_DIR",
)


def make(monkeypatch, **env):
    for key in CLEARED:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


# ---------------------------------------------------------------- defaults
def test_evaluation_defaults_are_safe_and_conservative(monkeypatch):
    s = make(monkeypatch)
    assert s.evaluation_provider == "mock"
    assert s.evaluation_model == "gpt-4o"
    assert s.evaluation_timeout_seconds == 60
    assert s.evaluation_max_retries == 3
    assert s.evaluation_retry_backoff_seconds == 5
    assert s.rubrics_dir is None


def test_default_rubrics_directory_exists_and_contains_the_default_rubric(monkeypatch):
    s = make(monkeypatch)
    assert s.rubrics_path == DEFAULT_RUBRICS_DIR
    assert (s.rubrics_path / "default.yaml").is_file()


def test_rubrics_dir_can_be_overridden_and_blank_means_default(monkeypatch, tmp_path):
    assert make(monkeypatch, RUBRICS_DIR=str(tmp_path)).rubrics_path == tmp_path
    assert make(monkeypatch, RUBRICS_DIR="   ").rubrics_path == DEFAULT_RUBRICS_DIR


def test_evaluation_values_can_be_configured(monkeypatch):
    s = make(monkeypatch, EVALUATION_MODEL="  gpt-4o-mini ", EVALUATION_TIMEOUT_SECONDS="90",
             EVALUATION_MAX_RETRIES="0", EVALUATION_RETRY_BACKOFF_SECONDS="10")
    assert (s.evaluation_model, s.evaluation_timeout_seconds) == ("gpt-4o-mini", 90)
    assert (s.evaluation_max_retries, s.evaluation_retry_backoff_seconds) == (0, 10)


# ---------------------------------------------------------------- provider rules
def test_mock_evaluation_provider_is_refused_in_production(monkeypatch):
    with pytest.raises(ValidationError, match="EVALUATION_PROVIDER=mock"):
        make(monkeypatch, ENVIRONMENT="production", TRANSCRIPTION_PROVIDER="local", EVALUATION_PROVIDER="mock")


def test_production_never_falls_back_silently_to_the_mock_evaluator(monkeypatch):
    """EVALUATION_PROVIDER not set at all: the default is mock, so production must refuse to start."""
    with pytest.raises(ValidationError, match="EVALUATION_PROVIDER=mock"):
        make(monkeypatch, ENVIRONMENT="production", TRANSCRIPTION_PROVIDER="local")


def test_mock_evaluation_is_allowed_in_development_and_test(monkeypatch):
    assert make(monkeypatch, ENVIRONMENT="development").evaluation_provider == "mock"
    assert make(monkeypatch, ENVIRONMENT="test").evaluation_provider == "mock"


def test_openai_evaluation_needs_a_server_side_key(monkeypatch):
    with pytest.raises(ValidationError, match="EVALUATION_PROVIDER=openai needs OPENAI_API_KEY"):
        make(monkeypatch, EVALUATION_PROVIDER="openai")
    with pytest.raises(ValidationError):
        make(monkeypatch, EVALUATION_PROVIDER="openai", OPENAI_API_KEY="   ")


def test_production_with_a_real_evaluation_provider_is_accepted(monkeypatch):
    s = make(monkeypatch, ENVIRONMENT="production", TRANSCRIPTION_PROVIDER="local",
             EVALUATION_PROVIDER="openai", OPENAI_API_KEY="sk-test-123")
    assert s.environment == "production" and s.evaluation_provider == "openai"


def test_unsupported_evaluation_provider_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, EVALUATION_PROVIDER="gemini")  # Gemini is not implemented yet
    with pytest.raises(ValidationError):
        make(monkeypatch, EVALUATION_PROVIDER="")


# ---------------------------------------------------------------- bounds
@pytest.mark.parametrize(
    "name, value",
    [
        ("EVALUATION_TIMEOUT_SECONDS", "1"), ("EVALUATION_TIMEOUT_SECONDS", "301"),
        ("EVALUATION_MAX_RETRIES", "-1"), ("EVALUATION_MAX_RETRIES", "11"),
        ("EVALUATION_RETRY_BACKOFF_SECONDS", "0"), ("EVALUATION_RETRY_BACKOFF_SECONDS", "301"),
        ("EVALUATION_TIMEOUT_SECONDS", "soon"),
    ],
)
def test_evaluation_limits_are_bounded(monkeypatch, name, value):
    with pytest.raises(ValidationError):
        make(monkeypatch, **{name: value})


@pytest.mark.parametrize("value", ["", "   ", "x" * 101])
def test_evaluation_model_must_be_non_empty_and_fit_the_database_column(monkeypatch, value):
    with pytest.raises(ValidationError):
        make(monkeypatch, EVALUATION_MODEL=value)


# ---------------------------------------------------------------- API keys
def test_existing_api_key_settings_are_preserved_as_hidden_secrets(monkeypatch):
    s = make(monkeypatch, OPENAI_API_KEY="sk-openai-secret-1", GEMINI_API_KEY="gem-secret-2",
             EVALUATION_PROVIDER="openai")
    assert isinstance(s.openai_api_key, SecretStr) and isinstance(s.gemini_api_key, SecretStr)
    assert s.openai_api_key.get_secret_value() == "sk-openai-secret-1"
    text = repr(s) + str(s.model_dump())
    assert "sk-openai-secret-1" not in text and "gem-secret-2" not in text


# ---------------------------------------------------------------- packaging / configuration consistency (static)
@needs_repo
def test_pyyaml_is_pinned_in_runtime_requirements_so_docker_installs_it():
    runtime = (ROOT / "backend" / "requirements.txt").read_text()
    assert re.search(r"^PyYAML==\d+\.\d+\.\d+\s*$", runtime, flags=re.MULTILINE)
    assert "-r requirements.txt" in (ROOT / "backend" / "requirements-dev.txt").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "pip install -r requirements.txt" in dockerfile  # the runtime file, not the dev file
    assert "requirements-dev" not in dockerfile
    assert "COPY backend/ ./" in dockerfile  # also copies backend/config/rubrics into the image


@needs_repo
def test_dockerignore_does_not_exclude_rubric_files():
    patterns = [l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines() if l.strip() and not l.startswith("#")]
    for blocked in ("config", "config/", "backend/config", "*.yaml", "*.yml", "**/*.yaml"):
        assert blocked not in patterns


@needs_repo
def test_env_example_lists_every_evaluation_setting_with_safe_values():
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    expected = {"EVALUATION_PROVIDER", "EVALUATION_MODEL", "EVALUATION_TIMEOUT_SECONDS",
                "EVALUATION_MAX_RETRIES", "EVALUATION_RETRY_BACKOFF_SECONDS"}
    assert expected <= set(values)
    fields = {name.upper() for name in Settings.model_fields}
    assert expected <= fields and "RUBRICS_DIR" in fields
    assert values["EVALUATION_PROVIDER"] == "mock" and values["OPENAI_API_KEY"] == ""
    # The documented example values must themselves be valid settings.
    Settings(_env_file=None, **{k.lower(): v for k, v in values.items() if k in expected},
             database_url="sqlite://", secret_key="x" * 48)


@needs_repo
def test_compose_passes_evaluation_settings_to_backend_and_worker():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for service in ("backend", "worker"):
        env = compose["services"][service]["environment"]
        for key in ("EVALUATION_PROVIDER", "EVALUATION_MODEL", "EVALUATION_TIMEOUT_SECONDS",
                    "EVALUATION_MAX_RETRIES", "EVALUATION_RETRY_BACKOFF_SECONDS"):
            assert key in env, f"{key} missing for {service}"
        assert "sk-" not in str(env)
