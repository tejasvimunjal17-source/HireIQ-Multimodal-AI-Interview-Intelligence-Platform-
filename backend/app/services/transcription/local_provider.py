"""Open-source Whisper running on this machine (package `openai-whisper`, needs PyTorch + ffmpeg).

Not installed by default (it is large). Install with:  pip install -r requirements-whisper-local.txt
The model is loaded once per worker process and reused.
"""

import logging
from pathlib import Path

from app.services.transcription.base import TranscriptionError, TranscriptionProvider, TranscriptionResult

logger = logging.getLogger(__name__)
_MODELS: dict[str, object] = {}  # per-process cache (model weights only; no candidate data)


class LocalWhisperProvider(TranscriptionProvider):
    name = "local"

    def __init__(self, model_name: str = "base") -> None:
        self._model_name = model_name

    def _load(self):
        if self._model_name not in _MODELS:
            try:
                import whisper  # type: ignore[import-not-found]
            except ImportError:
                raise TranscriptionError(
                    "provider_not_installed",
                    "The 'openai-whisper' package is not installed (see requirements-whisper-local.txt).",
                    retryable=False,
                )
            _MODELS[self._model_name] = whisper.load_model(self._model_name)
        return _MODELS[self._model_name]

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> TranscriptionResult:
        model = self._load()
        try:
            result = model.transcribe(str(audio_path), language=language, fp16=False)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local Whisper failed: %s", type(exc).__name__)
            raise TranscriptionError("provider_error", "Local Whisper failed to transcribe the audio.", retryable=True)
        segments = [
            {"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip()}
            for s in result.get("segments", [])
        ]
        duration = segments[-1]["end"] if segments else None
        return TranscriptionResult(
            text=str(result.get("text", "")).strip(), language=result.get("language"),
            duration_seconds=duration, segments=segments, provider=self.name, model=self._model_name,
        )
