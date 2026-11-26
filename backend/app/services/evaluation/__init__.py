"""LLM evaluation (Day 4). Phase 2: prompt construction. Phase 3: providers/, scoring, pipeline, engine, coordination.

The heavier modules (engine, coordination) are imported explicitly, not here, so that the prompt builder and the
database-free pipeline can be imported without a database driver."""

from app.services.evaluation.prompt_builder import (
    PROMPT_VERSION,
    EmptyTranscriptError,
    EvaluationPrompt,
    PromptBuildError,
    TranscriptTooLongError,
    build_evaluation_prompt,
)

__all__ = [
    "PROMPT_VERSION", "EmptyTranscriptError", "EvaluationPrompt", "PromptBuildError",
    "TranscriptTooLongError", "build_evaluation_prompt",
]
