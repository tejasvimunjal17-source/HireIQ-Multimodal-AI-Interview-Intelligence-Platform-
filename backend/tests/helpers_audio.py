"""Generate real audio test files (WAV with the standard library; other formats with the ffmpeg program)."""

import io
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def wav_bytes(seconds: float = 1.0, rate: int = 44100, channels: int = 2, amplitude: int = 12000, freq: int = 440) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            sample = int(amplitude * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", sample) * channels
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def silent_wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    return wav_bytes(seconds, rate, 1, amplitude=0)


# ffmpeg output settings per container
_FFMPEG_CODECS = {"webm": ["-c:a", "libopus"], "ogg": ["-c:a", "libopus"], "mp4": ["-c:a", "aac"], "mp3": ["-c:a", "libmp3lame"]}


def ffmpeg_audio(path: Path, seconds: float = 1.0) -> Path:
    """Create a real encoded sine-tone file; the format follows the file extension."""
    fmt = path.suffix.lstrip(".")
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={seconds}", "-ac", "2", "-ar", "48000", *_FFMPEG_CODECS[fmt], str(path),
    ]
    subprocess.run(command, check=True, timeout=60)
    return path
