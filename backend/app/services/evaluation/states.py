"""Pure answer/session state rules (no database, no model imports). Status values are compared as plain
strings, which equal the StrEnum members used by the models ("pending" == TranscriptionStatus.PENDING).
See coordination.py for how they are applied."""

from __future__ import annotations

from enum import StrEnum

class ResponseState(StrEnum):
    TRANSCRIPTION_OPEN = "transcription_open"
    TRANSCRIPTION_FAILED = "transcription_failed"
    NO_SPEECH = "no_speech"
    MISSING_TRANSCRIPT = "missing_transcript"
    EVALUATION_OPEN = "evaluation_open"
    EVALUATED = "evaluated"
    EVALUATION_FAILED = "evaluation_failed"
    EVALUATION_SKIPPED = "evaluation_skipped"


_UNFINISHED = {ResponseState.TRANSCRIPTION_OPEN, ResponseState.EVALUATION_OPEN}
_FAILURES = {ResponseState.TRANSCRIPTION_FAILED, ResponseState.MISSING_TRANSCRIPT, ResponseState.EVALUATION_FAILED}


def classify_response(
    transcription_status: str,
    no_speech_detected: bool,
    transcript_length: int,
    evaluation_status: str,
) -> ResponseState:
    if transcription_status in ("pending", "processing"):
        return ResponseState.TRANSCRIPTION_OPEN
    if transcription_status == "failed":
        return ResponseState.TRANSCRIPTION_FAILED
    # transcription COMPLETED from here on
    if no_speech_detected:
        return ResponseState.NO_SPEECH
    if transcript_length <= 0:
        return ResponseState.MISSING_TRANSCRIPT
    return {
        "pending": ResponseState.EVALUATION_OPEN,
        "processing": ResponseState.EVALUATION_OPEN,
        "completed": ResponseState.EVALUATED,
        "failed": ResponseState.EVALUATION_FAILED,
        "skipped": ResponseState.EVALUATION_SKIPPED,
    }[evaluation_status]


def decide_session_status(states: list[ResponseState]) -> str | None:
    if not states:
        return None
    if any(s in _UNFINISHED for s in states):
        return "processing"
    if ResponseState.EVALUATED in states and not any(s in _FAILURES for s in states):
        return "evaluated"
    return "failed"


