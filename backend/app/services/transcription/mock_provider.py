"""Mock provider for development and automated tests. NO speech recognition happens here."""

import wave
from pathlib import Path

from app.services.transcription.base import TranscriptionProvider, TranscriptionResult

MOCK_TEXT = "[MOCK TRANSCRIPT] Placeholder text. No speech recognition was performed."


class MockProvider(TranscriptionProvider):
    name = "mock"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> TranscriptionResult:
        duration = None
        try:
            with wave.open(str(audio_path), "rb") as handle:
                duration = handle.getnframes() / float(handle.getframerate())
        except (wave.Error, EOFError, OSError):
            pass
        segments = [{"start": 0.0, "end": round(duration or 0.0, 3), "text": MOCK_TEXT}]
        return TranscriptionResult(
            text=MOCK_TEXT, language=language or "en", duration_seconds=duration,
            segments=segments, provider=self.name, model="mock-v1",
        )
