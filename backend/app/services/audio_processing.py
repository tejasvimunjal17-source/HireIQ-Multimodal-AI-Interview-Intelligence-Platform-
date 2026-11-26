"""PyDub-based preparation of uploaded audio for speech-to-text.

Pipeline:  validate source -> decode (bounded) -> check duration -> mono / 16 kHz / 16-bit
           -> silence check -> peak-normalize -> write prepared.wav in a private scratch folder.

Decoding non-WAV formats needs the `ffmpeg` program (installed in the Docker image).
"""

import logging
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

from app.services.audio_intake import detect_audio_format

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD_DBFS = -60.0  # quieter than this (average level) is treated as "no speech"
NORMALIZE_HEADROOM_DB = 1.0
MAX_PREPARED_BYTES = 24 * 1024 * 1024  # OpenAI's upload limit is 25 MB
HEADER_SIZE = 32


class AudioProcessingError(Exception):
    """The audio cannot be processed.

    delete_audio=True  the FILE is bad (empty, corrupt, spoofed, too long...): retrying is pointless
    delete_audio=False the SERVER is missing something (e.g. ffmpeg): keep the audio so it can be retried
    """

    def __init__(self, code: str, message: str, *, delete_audio: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.delete_audio = delete_audio


@dataclass(frozen=True)
class ProcessedAudio:
    path: Path | None  # None when the recording is silent (nothing to send to a provider)
    duration_seconds: float
    is_silent: bool
    source_format: str
    source_channels: int
    source_sample_rate: int


def validate_source_file(path: Path) -> str:
    """Check the file on disk really is one of the supported audio containers. Returns its format."""
    if not path.is_file():
        raise AudioProcessingError("audio_missing", "The audio file is no longer available.", delete_audio=False)
    if path.stat().st_size == 0:
        raise AudioProcessingError("audio_empty", "The audio file is empty.")
    with open(path, "rb") as handle:
        detected = detect_audio_format(handle.read(HEADER_SIZE))
    if detected is None or path.suffix.lstrip(".").lower() != detected:
        raise AudioProcessingError("audio_unsupported", "The file is not a supported audio format.")
    return detected


def _decode(source: Path, fmt: str, max_duration_seconds: int):
    # Imported here so the rest of the app (and the unit tests that do not need audio) load without pydub.
    from pydub import AudioSegment
    from pydub.exceptions import CouldntDecodeError

    if fmt != "wav" and shutil.which("ffmpeg") is None:
        raise AudioProcessingError(
            "decoder_unavailable", "ffmpeg is not installed on the server.", delete_audio=False
        )
    kwargs = {}
    if fmt != "wav":
        # Never decode more than max+1 seconds: a small compressed file can expand to gigabytes of PCM.
        kwargs["duration"] = max_duration_seconds + 1
    try:
        return AudioSegment.from_file(str(source), format=fmt, **kwargs)
    except FileNotFoundError:
        raise AudioProcessingError("decoder_unavailable", "ffmpeg is not installed on the server.", delete_audio=False)
    except (CouldntDecodeError, IndexError, EOFError, wave.Error, ValueError, OSError):
        raise AudioProcessingError("audio_corrupt", "The audio could not be decoded (corrupted file).")


def prepare_for_transcription(
    source: Path,
    work_dir: Path,
    *,
    max_duration_seconds: int,
    min_duration_ms: int,
    target_sample_rate: int = 16000,
) -> ProcessedAudio:
    """Turn an uploaded recording into `work_dir/prepared.wav` (mono, 16-bit, target_sample_rate)."""
    fmt = validate_source_file(source)
    segment = _decode(source, fmt, max_duration_seconds)

    source_channels, source_rate = segment.channels, segment.frame_rate
    duration_ms = len(segment)
    if duration_ms == 0:
        raise AudioProcessingError("audio_empty", "The recording contains no audio.")
    if duration_ms < min_duration_ms:
        raise AudioProcessingError("audio_too_short", "The recording is too short.")
    if duration_ms > max_duration_seconds * 1000:
        raise AudioProcessingError(
            "audio_too_long", f"The recording is longer than the {max_duration_seconds} second limit."
        )

    segment = segment.set_channels(1).set_frame_rate(target_sample_rate).set_sample_width(2)

    if segment.dBFS < SILENCE_THRESHOLD_DBFS:  # also true for digital silence (-inf)
        return ProcessedAudio(None, duration_ms / 1000, True, fmt, source_channels, source_rate)

    from pydub.effects import normalize

    segment = normalize(segment, headroom=NORMALIZE_HEADROOM_DB)
    out_path = work_dir / "prepared.wav"
    segment.export(str(out_path), format="wav")
    if out_path.stat().st_size > MAX_PREPARED_BYTES:
        out_path.unlink(missing_ok=True)
        raise AudioProcessingError("audio_too_long", "The prepared audio is too large to transcribe.")
    return ProcessedAudio(out_path, duration_ms / 1000, False, fmt, source_channels, source_rate)
