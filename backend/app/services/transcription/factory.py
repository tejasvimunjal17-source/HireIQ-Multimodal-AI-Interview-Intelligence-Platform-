from app.core.config import Settings
from app.services.transcription.base import TranscriptionError, TranscriptionProvider
from app.services.transcription.local_provider import LocalWhisperProvider
from app.services.transcription.mock_provider import MockProvider
from app.services.transcription.openai_provider import OpenAIWhisperProvider


def get_provider(settings: Settings) -> TranscriptionProvider:
    """Build the provider selected by TRANSCRIPTION_PROVIDER."""
    name = settings.transcription_provider
    if name == "mock":
        return MockProvider()
    if name == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        return OpenAIWhisperProvider(
            api_key=key,
            model=settings.openai_transcription_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.transcription_timeout_seconds,
        )
    if name == "local":
        return LocalWhisperProvider(settings.local_whisper_model)
    raise TranscriptionError("provider_unknown", f"Unknown transcription provider '{name}'.", retryable=False)
