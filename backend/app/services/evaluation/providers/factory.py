"""Chooses the evaluation provider from settings. To add Gemini: write the provider class and add one
entry to PROVIDER_BUILDERS (and to the EVALUATION_PROVIDER setting's allowed values). Not implemented yet."""

from collections.abc import Callable

from app.core.config import Settings
from app.services.evaluation.providers.base import EvaluationProvider, EvaluationProviderError
from app.services.evaluation.providers.mock_provider import MockEvaluationProvider
from app.services.evaluation.providers.openai_provider import OpenAIEvaluationProvider


def _openai(settings: Settings) -> EvaluationProvider:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return OpenAIEvaluationProvider(
        api_key=key,
        model=settings.evaluation_model,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.evaluation_timeout_seconds,
    )


PROVIDER_BUILDERS: dict[str, Callable[[Settings], EvaluationProvider]] = {
    "mock": lambda settings: MockEvaluationProvider(),
    "openai": _openai,
}


def get_evaluation_provider(settings: Settings) -> EvaluationProvider:
    builder = PROVIDER_BUILDERS.get(settings.evaluation_provider)
    if builder is None:
        raise EvaluationProviderError(
            "provider_unsupported", f"Unsupported EVALUATION_PROVIDER '{settings.evaluation_provider}'.", retryable=False
        )
    return builder(settings)
