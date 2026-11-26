"""OpenAI Chat Completions (POST {base_url}/chat/completions) in JSON mode.

The key comes from server-side settings (OPENAI_API_KEY, shared with transcription), is sent only in the
Authorization header, and never appears in logs, exceptions or repr(). Failure messages are fixed strings:
no prompt, transcript or model output is ever included.
"""

import logging

import requests

from app.services.evaluation.prompt_builder import EvaluationPrompt
from app.services.evaluation.providers.base import EvaluationProvider, EvaluationProviderError, ProviderOutput

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT_SECONDS = 10


def _retry_after_seconds(response: requests.Response) -> float | None:
    try:
        raw = response.headers.get("Retry-After")
        return max(0.0, float(raw)) if raw is not None else None
    except (ValueError, TypeError):
        return None


def _error_code(response: requests.Response) -> str:
    """OpenAI's error.code (e.g. 'insufficient_quota'); '' when unreadable."""
    try:
        error = response.json().get("error")
        code = error.get("code") if isinstance(error, dict) else None
        return code if isinstance(code, str) else ""
    except (ValueError, AttributeError):
        return ""


class OpenAIEvaluationProvider(EvaluationProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise EvaluationProviderError(
                "provider_not_configured", "OPENAI_API_KEY is not set on the server.", retryable=False
            )
        self._api_key = api_key
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = timeout_seconds
        self._session = session or requests.Session()

    def __repr__(self) -> str:  # never show the key
        return f"OpenAIEvaluationProvider(model={self.model!r})"

    def evaluate(self, prompt: EvaluationPrompt) -> ProviderOutput:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            response = self._session.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=(CONNECT_TIMEOUT_SECONDS, self._timeout),
            )
        except requests.Timeout:
            raise EvaluationProviderError("provider_timeout", "The evaluation service timed out.", retryable=True) from None
        except requests.RequestException as exc:
            logger.warning("Evaluation request failed: %s", type(exc).__name__)  # class only: text may hold URLs
            raise EvaluationProviderError("provider_unreachable", "Could not reach the evaluation service.", retryable=True) from None

        status = response.status_code
        if status == 429:
            if _error_code(response) == "insufficient_quota":  # billing problem: waiting will not help
                raise EvaluationProviderError("quota_exceeded", "The evaluation account has no quota left.", retryable=False)
            raise EvaluationProviderError(
                "rate_limited", "The evaluation service is rate limiting requests.",
                retryable=True, retry_after=_retry_after_seconds(response),
            )
        if status >= 500:
            raise EvaluationProviderError("provider_error", f"The evaluation service failed (HTTP {status}).", retryable=True)
        if status in (401, 403):
            raise EvaluationProviderError("provider_auth", "The evaluation service rejected the server credentials.", retryable=False)
        if status >= 400:
            raise EvaluationProviderError("provider_rejected", f"The evaluation service rejected the request (HTTP {status}).", retryable=False)

        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise EvaluationProviderError("provider_bad_response", "The evaluation service returned an unreadable response.", retryable=True) from None
        if message.get("refusal"):
            raise EvaluationProviderError("provider_refused", "The model refused to evaluate this answer.", retryable=False)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise EvaluationProviderError("provider_bad_response", "The evaluation service returned an empty answer.", retryable=True)
        if choice.get("finish_reason") == "length":  # cut off: the JSON cannot be complete
            raise EvaluationProviderError("provider_bad_response", "The evaluation answer was cut off.", retryable=True)

        reported = body.get("model")
        return ProviderOutput(
            raw_text=content,
            provider=self.name,
            model=(reported if isinstance(reported, str) and reported else self.model)[:100],
        )
