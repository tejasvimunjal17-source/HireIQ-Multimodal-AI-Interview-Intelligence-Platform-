"""Centralized application settings, loaded from environment variables.

Secrets (SECRET_KEY, DATABASE_URL, API keys) have NO defaults on purpose,
so the app can never silently start with a hardcoded credential.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_PREFIX = "change-me"
MIN_PRODUCTION_SECRET_LENGTH = 32
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
# Rubric YAML files live in backend/config/rubrics (also /app/config/rubrics inside the Docker image).
DEFAULT_RUBRICS_DIR = Path(__file__).resolve().parents[2] / "config" / "rubrics"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files override earlier ones. Real environment variables beat both.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds POSTGRES_* values used only by Docker
        case_sensitive=False,
    )

    app_name: str = "HireIQ API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Required (no defaults):
    database_url: str
    secret_key: SecretStr

    redis_url: str = "redis://localhost:6379/0"

    # Optional unless a provider that needs them is selected. SecretStr hides the value in repr()/logs.
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # Comma-separated string (easier in .env than JSON lists).
    cors_origins: str = "http://localhost:5173"

    # Audio upload (Day 2). Files are TEMPORARY: Day 3 deletes them after transcription,
    # and anything older than audio_stale_after_hours is purged at startup.
    audio_temp_dir: str = "/tmp/hireiq-audio"
    audio_max_upload_mb: int = Field(default=25, ge=1, le=200)
    audio_stale_after_hours: int = Field(default=24, ge=1, le=720)

    # Audio processing (Day 3)
    audio_max_duration_seconds: int = Field(default=600, ge=10, le=3600)
    audio_min_duration_ms: int = Field(default=300, ge=0, le=5000)
    audio_target_sample_rate: int = Field(default=16000, ge=8000, le=48000)

    # Transcription (Day 3). "mock" never calls any service and returns clearly fake text.
    transcription_provider: Literal["mock", "openai", "local"] = "mock"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_transcription_model: str = "whisper-1"
    local_whisper_model: str = "base"  # only used by provider "local"
    transcription_language: str | None = None  # None = auto-detect
    transcription_timeout_seconds: int = Field(default=120, ge=5, le=900)
    transcription_max_retries: int = Field(default=3, ge=0, le=10)  # automatic Celery retries
    transcription_max_attempts: int = Field(default=6, ge=1, le=50)  # automatic + manual, in total
    transcription_stuck_minutes: int = Field(default=30, ge=1, le=1440)

    # LLM evaluation (Day 4). "mock" never calls any service and returns clearly fake scores.
    # The API key is shared with transcription (OPENAI_API_KEY) and stays on the server.
    evaluation_provider: Literal["mock", "openai"] = "mock"
    evaluation_model: str = Field(default="gpt-4o", min_length=1, max_length=100)  # stored in evaluations.llm_model
    evaluation_timeout_seconds: int = Field(default=60, ge=5, le=300)
    evaluation_max_retries: int = Field(default=3, ge=0, le=10)  # automatic Celery retries
    evaluation_retry_backoff_seconds: int = Field(default=5, ge=1, le=300)  # base delay, grows per retry
    # Folder with the YAML rubric files. Blank = the built-in backend/config/rubrics folder.
    rubrics_dir: str | None = None

    # NLP enrichment (Day 5): spaCy keywords/entities, VADER sentiment, rule-based confidence signal.
    # Runs AFTER a successful LLM evaluation and never changes its score. The model is installed with pip
    # (see requirements.txt); the application never downloads it.
    nlp_enabled: bool = True
    nlp_spacy_model: str = Field(default="en_core_web_sm", pattern=r"^[A-Za-z0-9_.\-]{1,100}$")  # a package name, never a path

    # PDF report download (Day 6). The API has no user accounts yet, and the candidate knows their own session id,
    # so the report endpoint needs this shared secret (Authorization: Bearer <token>). Unset = downloads disabled.
    report_access_token: SecretStr | None = None

    @field_validator("report_access_token", mode="after")
    @classmethod
    def _report_token_is_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 16:
            raise ValueError("REPORT_ACCESS_TOKEN must be at least 16 characters (use a long random value).")
        return value

    @field_validator("openai_api_key", "gemini_api_key", "report_access_token", mode="before")
    @classmethod
    def _empty_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("transcription_language", mode="before")
    @classmethod
    def _blank_language_is_auto(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("rubrics_dir", mode="before")
    @classmethod
    def _blank_rubrics_dir_is_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("evaluation_model", mode="before")
    @classmethod
    def _strip_evaluation_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(VALID_LOG_LEVELS)}")
        return level

    @model_validator(mode="after")
    def _reject_weak_secret_in_production(self) -> "Settings":
        if self.environment == "production":
            secret = self.secret_key.get_secret_value()
            if secret.startswith(INSECURE_SECRET_PREFIX) or len(secret) < MIN_PRODUCTION_SECRET_LENGTH:
                raise ValueError(
                    "SECRET_KEY is a placeholder or too short for production "
                    f"(need at least {MIN_PRODUCTION_SECRET_LENGTH} random characters)."
                )
        return self

    @model_validator(mode="after")
    def _check_transcription_provider(self) -> "Settings":
        if self.transcription_provider == "mock" and self.environment == "production":
            raise ValueError("TRANSCRIPTION_PROVIDER=mock returns fake text and is not allowed in production.")
        if self.transcription_provider == "openai" and self.openai_api_key is None:
            raise ValueError("TRANSCRIPTION_PROVIDER=openai needs OPENAI_API_KEY (server-side .env only).")
        return self

    @model_validator(mode="after")
    def _check_evaluation_provider(self) -> "Settings":
        if self.evaluation_provider == "mock" and self.environment == "production":
            raise ValueError("EVALUATION_PROVIDER=mock returns fake scores and is not allowed in production.")
        if self.evaluation_provider == "openai" and self.openai_api_key is None:
            raise ValueError("EVALUATION_PROVIDER=openai needs OPENAI_API_KEY (server-side .env only).")
        return self

    @property
    def rubrics_path(self) -> Path:
        return Path(self.rubrics_dir) if self.rubrics_dir else DEFAULT_RUBRICS_DIR

    @property
    def audio_max_upload_bytes(self) -> int:
        return self.audio_max_upload_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
