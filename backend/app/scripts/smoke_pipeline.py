"""End-to-end check of the Day 3 pipeline against a RUNNING stack.

    docker compose exec -T backend python -m app.scripts.smoke_pipeline
    docker compose exec -T backend python -m app.scripts.smoke_pipeline --audio /path/answer.webm --show-text

Creates a throw-away candidate, uploads one answer, waits for the Celery worker to transcribe it,
and checks that the raw audio was deleted. With TRANSCRIPTION_PROVIDER=mock this proves the pipeline
(API -> Redis -> worker -> PostgreSQL), NOT speech recognition. With provider=openai/local and a REAL
speech recording (--audio) it is a real transcription test.
"""

import argparse
import io
import math
import struct
import sys
import time
import uuid
import wave

import requests

from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory
from app.services.audio_intake import detect_audio_format, find_audio_path
from app.services.demo_seed import seed_demo_interview

CONTENT_TYPES = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav"}


def make_tone_wav(seconds: float = 2.0, rate: int = 44100) -> bytes:
    """A stereo 440 Hz tone. It is NOT speech: a real provider will return empty/odd text for it."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            sample = int(16000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<hh", sample, sample)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--audio", help="path to a real recording (webm/ogg/mp4/mp3/wav); default is a test tone")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for the transcription")
    parser.add_argument("--show-text", action="store_true", help="print the first 120 characters of the transcript")
    args = parser.parse_args()

    settings = get_settings()
    print(f"provider={settings.transcription_provider} base_url={args.base_url}")

    with get_session_factory()() as db:
        interview, _ = seed_demo_interview(db)
        interview_id = str(interview.id)
    dispose_engine()

    if args.audio:
        data = open(args.audio, "rb").read()
        fmt = detect_audio_format(data[:32])
        if fmt is None:
            print("FAIL: --audio is not a supported audio file")
            return 1
    else:
        data, fmt = make_tone_wav(), "wav"

    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    session = requests.post(
        f"{args.base_url}/api/sessions",
        json={"interview_id": interview_id, "candidate_name": "Smoke Test", "candidate_email": email, "consent": True},
        timeout=20,
    )
    session.raise_for_status()
    view = session.json()
    session_id, question_id = view["session_id"], view["questions"][0]["id"]

    upload = requests.post(
        f"{args.base_url}/api/sessions/{session_id}/responses",
        data={"question_id": question_id, "duration_seconds": "2"},
        files={"audio": (f"answer.{fmt}", data, CONTENT_TYPES[fmt])},
        timeout=60,
    )
    upload.raise_for_status()
    receipt = upload.json()
    print(f"upload accepted: HTTP {upload.status_code}, task_id={receipt.get('task_id')}")
    if not receipt.get("task_id"):
        print("FAIL: no task id returned (is Redis reachable?)")
        return 1

    deadline = time.time() + args.timeout
    status = None
    while time.time() < deadline:
        items = requests.get(f"{args.base_url}/api/sessions/{session_id}/transcriptions", timeout=20).json()
        status = items[0]
        print(f"  status={status['status']} attempts={status['attempts']}")
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(2)

    if not status or status["status"] != "completed":
        print(f"FAIL: transcription did not complete (last status: {status and status['status']}, "
              f"error: {status and status['error_code']})")
        return 1

    text = status["transcript"] or ""
    deleted = find_audio_path(uuid.UUID(receipt["response_id"]), settings.audio_temp_dir) is None
    print(f"completed: provider={status['provider']} language={status['language']} "
          f"duration={status['duration_seconds']} chars={len(text)} no_speech={status['no_speech_detected']}")
    print(f"raw audio deleted after transcription: {deleted}")
    if args.show_text:
        print("transcript (first 120 chars):", text[:120])
    if not deleted:
        print("FAIL: raw audio still on disk")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
