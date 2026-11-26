"""STATIC checks of repository files (no services). Skipped inside the Docker image,
which only contains the backend folder."""

import re
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings

pytestmark = pytest.mark.static

ROOT = Path(__file__).resolve().parents[2]
needs_repo = pytest.mark.skipif(
    not (ROOT / "docker-compose.yml").exists(),
    reason="repository root files not present (running inside the backend-only Docker image)",
)

REQUIRED_ENV_KEYS = {
    "DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "REDIS_URL",
    "SECRET_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "CORS_ORIGINS",
}


def read_env_example() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


@needs_repo
def test_env_example_has_all_required_keys_and_only_placeholders():
    values = read_env_example()
    assert REQUIRED_ENV_KEYS <= set(values)
    assert values["OPENAI_API_KEY"] == "" and values["GEMINI_API_KEY"] == ""
    assert values["SECRET_KEY"].startswith("change-me")
    assert not re.search(r"sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{20,}", (ROOT / ".env.example").read_text())


@needs_repo
def test_every_env_example_app_setting_matches_a_settings_field():
    app_keys = REQUIRED_ENV_KEYS - {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}
    fields = {name.upper() for name in Settings.model_fields}
    assert app_keys <= fields


@needs_repo
def test_gitignore_excludes_secrets_caches_and_candidate_data():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text().splitlines()}
    for required in (".env", ".venv/", "__pycache__/", ".pytest_cache/", "*.log", "*.sqlite3", "uploads/", "*.wav"):
        assert required in lines, f"{required} missing from .gitignore"
    assert "!.env.example" in lines


@needs_repo
def test_docker_compose_is_consistent():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert {"backend", "postgres", "redis", "worker"} <= set(services)

    for name in ("postgres", "redis", "backend"):
        assert "healthcheck" in services[name], f"{name} has no healthcheck"
    assert services["backend"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["backend"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "celery" in " ".join(services["worker"]["command"])

    assert "postgres_data" in compose["volumes"]
    assert any("postgres_data" in v for v in services["postgres"]["volumes"])

    backend_env = services["backend"]["environment"]
    assert "@postgres:5432" in backend_env["DATABASE_URL"]
    assert backend_env["REDIS_URL"] == "redis://redis:6379/0"
    assert services["worker"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"

    # No hardcoded secrets: passwords must come from ${VARIABLES}.
    text = (ROOT / "docker-compose.yml").read_text()
    for line in text.splitlines():
        if "PASSWORD" in line.upper() and not line.strip().startswith("#"):
            assert "${" in line, f"hardcoded password-like value: {line.strip()}"
    # Database/Redis are not published to the host.
    assert "ports" not in services["postgres"] and "ports" not in services["redis"]


@needs_repo
def test_dockerfile_basics():
    text = (ROOT / "Dockerfile").read_text()
    assert "python:3.12" in text
    assert "USER app" in text
    assert "backend/requirements.txt" in text


@needs_repo
def test_requirements_pin_every_package():
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / "backend" / name).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-r")):
                assert "==" in line, f"{name}: '{line}' is not pinned"


@needs_repo
def test_audio_temp_volume_is_shared_by_backend_and_worker_and_env_documented():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert "audio_tmp" in compose["volumes"]
    for name in ("backend", "worker"):
        assert any(v.startswith("audio_tmp:") for v in compose["services"][name]["volumes"])
    assert "AUDIO_MAX_UPLOAD_MB" in read_env_example()
    assert "audio_max_upload_mb" in Settings.model_fields


@needs_repo
def test_day3_docker_ci_and_env_configuration():
    assert "ffmpeg" in (ROOT / "Dockerfile").read_text()
    env = read_env_example()
    assert env["TRANSCRIPTION_PROVIDER"] == "mock" and env["OPENAI_API_KEY"] == ""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for name in ("backend", "worker"):
        assert compose["services"][name]["environment"]["TRANSCRIPTION_PROVIDER"]
    requirements = (ROOT / "backend" / "requirements.txt").read_text()
    assert "pydub==" in requirements and "requests==" in requirements
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ffmpeg" in ci and "smoke_pipeline" in ci
    real = (ROOT / ".github" / "workflows" / "real-whisper.yml").read_text()
    assert "workflow_dispatch" in real and "secrets.OPENAI_API_KEY" in real
    assert "sk-" not in real and "sk-" not in ci
