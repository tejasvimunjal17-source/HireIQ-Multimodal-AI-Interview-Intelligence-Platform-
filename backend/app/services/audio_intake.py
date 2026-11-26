"""Safe intake of uploaded candidate audio.

Rules (internship brief + Day 2 prompt):
- Never trust the browser's filename or declared type: we sniff the file header.
- Store only in a private temp directory, under a server-generated name.
- Never expose files through a URL. Audio is TEMPORARY (deleted after Day 3 transcription,
  or purged when stale).
"""

import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
HEADER_SIZE = 32

# declared MIME type -> audio family
DECLARED_TYPES: dict[str, str] = {
    "audio/webm": "webm",
    "video/webm": "webm",  # some browsers label audio-only WebM this way
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/x-m4a": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}
EXTENSIONS = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "mp3": "mp3", "wav": "wav"}
KNOWN_SUFFIXES = {f".{ext}" for ext in EXTENSIONS.values()} | {".part"}
WORK_DIR_NAME = ".work"  # per-attempt scratch folders for audio processing live here


class AudioValidationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class SavedAudio:
    path: Path
    size_bytes: int
    content_type: str
    audio_format: str


def normalize_content_type(raw: str | None) -> str:
    """'audio/webm;codecs=opus' -> 'audio/webm'"""
    return (raw or "").split(";")[0].strip().lower()


def detect_audio_format(header: bytes) -> str | None:
    """Identify the audio container from its first bytes."""
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if header.startswith(b"OggS"):
        return "ogg"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "wav"
    if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def ensure_audio_dir(directory: str) -> Path:
    path = Path(directory)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def save_upload(upload: UploadFile, response_id: uuid.UUID, directory: str, max_bytes: int) -> SavedAudio:
    """Validate and store one upload. Raises AudioValidationError; leaves no partial file behind."""
    content_type = normalize_content_type(upload.content_type)
    expected_format = DECLARED_TYPES.get(content_type)
    if expected_format is None:
        raise AudioValidationError(415, f"Unsupported audio type '{content_type or 'unknown'}'.")

    header = upload.file.read(HEADER_SIZE)
    if not header:
        raise AudioValidationError(400, "The uploaded audio is empty.")
    detected = detect_audio_format(header)
    if detected is None or detected != expected_format:
        raise AudioValidationError(415, "The file content does not match a supported audio format.")

    target_dir = ensure_audio_dir(directory)
    partial = target_dir / f"{response_id}.part"
    final = target_dir / f"{response_id}.{EXTENSIONS[detected]}"
    total = 0
    try:
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            chunk = header
            while chunk:
                total += len(chunk)
                if total > max_bytes:
                    raise AudioValidationError(413, f"Audio is larger than the {max_bytes // (1024 * 1024)} MB limit.")
                out.write(chunk)
                chunk = upload.file.read(CHUNK_SIZE)
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
    return SavedAudio(path=final, size_bytes=total, content_type=content_type, audio_format=detected)


def find_audio_path(response_id: uuid.UUID, directory: str) -> Path | None:
    """Where the transcription worker finds the stored audio for a response."""
    for ext in EXTENSIONS.values():
        candidate = Path(directory) / f"{response_id}.{ext}"
        if candidate.exists():
            return candidate
    return None


def delete_audio(response_id: uuid.UUID, directory: str) -> None:
    for suffix in KNOWN_SUFFIXES:
        (Path(directory) / f"{response_id}{suffix}").unlink(missing_ok=True)


def make_work_dir(directory: str, response_id: uuid.UUID) -> Path:
    """A fresh private scratch folder for ONE processing attempt (unique per attempt, so workers
    can never touch each other's intermediate files). Caller must remove it (shutil.rmtree)."""
    root = ensure_audio_dir(directory) / WORK_DIR_NAME
    root.mkdir(mode=0o700, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{response_id}-", dir=root))  # mkdtemp creates it with mode 0700


def purge_stale_audio(directory: str, max_age_seconds: float, now: float | None = None) -> int:
    """Delete temp audio older than max_age_seconds. Returns how many files were removed."""
    root = Path(directory)
    if not root.is_dir():
        return 0
    current = time.time() if now is None else now
    removed = 0
    for item in root.iterdir():
        if item.is_file() and item.suffix in KNOWN_SUFFIXES and current - item.stat().st_mtime > max_age_seconds:
            item.unlink(missing_ok=True)
            removed += 1
    work = root / WORK_DIR_NAME
    if work.is_dir():  # scratch folders left behind by crashed workers
        for leftover in work.iterdir():
            if leftover.is_dir() and current - leftover.stat().st_mtime > max_age_seconds:
                shutil.rmtree(leftover, ignore_errors=True)
                removed += 1
    if removed:
        logger.info("Purged %d stale audio file(s)/folder(s)", removed)
    return removed
