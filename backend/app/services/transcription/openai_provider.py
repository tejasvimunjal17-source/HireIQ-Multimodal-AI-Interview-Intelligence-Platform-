"""OpenAI Whisper API (POST {base_url}/audio/transcriptions).

The API key is read from server-side settings only and is sent in an Authorization header.
It is never logged and never put in an exception message.
"""

import logging
from pathlib import Path

import requests

from app.services.transcription.base import TranscriptionError, TranscriptionProvider, TranscriptionResult

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT_SECONDS = 10


def _retry_after_seconds(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


class OpenAIWhisperProvider(TranscriptionProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 120,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise TranscriptionError(
                "provider_not_configured", "OPENAI_API_KEY is not set on the server.", retryable=False
            )
        self._api_key = api_key
        self._model = model
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._timeout = timeout_seconds
        self._session = session or requests.Session()

    def __repr__(self) -> str:  # never show the key
        return f"OpenAIWhisperProvider(model={self._model!r})"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> TranscriptionResult:
        data = {"model": self._model, "response_format": "verbose_json", "timestamp_granularities[]": "segment"}
        if language:
            data["language"] = language
        try:
            with open(audio_path, "rb") as handle:
                response = self._session.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": ("answer.wav", handle, "audio/wav")},
                    timeout=(CONNECT_TIMEOUT_SECONDS, self._timeout),
                )
        except requests.Timeout:
            raise TranscriptionError("provider_timeout", "The transcription service timed out.", retryable=True)
        except requests.RequestException as exc:
            # Only the exception class: its text may contain URLs or headers.
            logger.warning("Transcription request failed: %s", type(exc).__name__)
            raise TranscriptionError("provider_unreachable", "Could not reach the transcription service.", retryable=True)

        status = response.status_code
        if status == 429:
            raise TranscriptionError(
                "rate_limited", "The transcription service is rate limiting requests.",
                retryable=True, retry_after=_retry_after_seconds(response),
            )
        if status >= 500:
            raise TranscriptionError("provider_error", f"The transcription service failed (HTTP {status}).", retryable=True)
        if status in (401, 403):
            raise TranscriptionError("provider_auth", "The transcription service rejected the server credentials.", retryable=False)
        if status >= 400:
            raise TranscriptionError("provider_rejected_audio", f"The transcription service rejected the request (HTTP {status}).", retryable=False)

        try:
            body = response.json()
            text = body["text"]
            if not isinstance(text, str):
                raise ValueError("text is not a string")
        except (ValueError, KeyError, TypeError):
            raise TranscriptionError("provider_bad_response", "The transcription service returned an unreadable response.", retryable=True)

        return TranscriptionResult(
            text=text.strip(),
            language=(str(body["language"])[:16] if body.get("language") else None),
            duration_seconds=_to_float(body.get("duration")),
            segments=_clean_segments(body.get("segments")),
            provider=self.name,
            model=self._model,
        )


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clean_segments(raw: object) -> list[dict]:
    cleaned: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                start, end = _to_float(item.get("start")), _to_float(item.get("end"))
                if start is not None and end is not None:
                    cleaned.append({"start": start, "end": end, "text": item["text"].strip()})
    return cleaned
