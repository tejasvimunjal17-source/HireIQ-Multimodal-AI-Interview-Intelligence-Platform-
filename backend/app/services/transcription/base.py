"""Provider-independent types for speech-to-text.

To add another provider (e.g. Azure, Deepgram): subclass TranscriptionProvider, raise
TranscriptionError for failures, and register it in factory.get_provider().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


class TranscriptionError(Exception):
    """A provider failure.

    code        short machine-readable reason, stored in the database (never contains transcript text)
    retryable   True for temporary problems (timeout, rate limit, 5xx); False for permanent ones
    retry_after seconds the provider asked us to wait (rate limits), if known
    """

    def __init__(self, code: str, message: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    segments: list[dict] = field(default_factory=list)  # [{"start": float, "end": float, "text": str}]
    provider: str = ""
    model: str | None = None

    @property
    def has_speech(self) -> bool:
        return bool(self.text.strip())


class TranscriptionProvider(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: Path, *, language: str | None = None) -> TranscriptionResult:
        """Transcribe a prepared audio file (16 kHz mono WAV). Raise TranscriptionError on failure."""
