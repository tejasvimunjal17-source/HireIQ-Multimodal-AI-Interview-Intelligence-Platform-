"""Provider-independent types for LLM evaluation (Day 4, Phase 3).

A provider receives the finished prompt and returns the model's RAW text. It never parses, scores or
validates: that is the engine's job, so every provider is held to the same rules.

To add another provider (e.g. Gemini): subclass EvaluationProvider, raise EvaluationProviderError for
failures, and register a builder in factory.PROVIDER_BUILDERS. Nothing else changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.services.evaluation.prompt_builder import EvaluationPrompt


class EvaluationProviderError(Exception):
    """A provider failure. `code` is a short machine code (stored in the database, safe to log).

    retryable   True for temporary problems (timeout, rate limit, 5xx, unreadable envelope)
    retry_after seconds the provider asked us to wait, if known
    The message never contains keys, prompts, transcripts or model output.
    """

    def __init__(self, code: str, message: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class ProviderOutput:
    raw_text: str = field(repr=False)  # the model's answer, still UNVALIDATED (may quote the transcript)
    provider: str
    model: str


class EvaluationProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def evaluate(self, prompt: EvaluationPrompt) -> ProviderOutput:
        """Send the prompt, return the raw JSON text. Raise EvaluationProviderError on failure."""
