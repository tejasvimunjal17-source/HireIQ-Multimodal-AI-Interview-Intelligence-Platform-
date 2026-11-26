"""Audio validation and temp-file handling (real code, real filesystem in tmp_path)."""

import io
import os
import re
import time
import uuid

import pytest
from starlette.datastructures import Headers, UploadFile

from app.services import audio_intake
from app.services.audio_intake import AudioValidationError, detect_audio_format, save_upload

SAMPLES = {
    "webm": (b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm"),
    "ogg": (b"OggS" + b"\x00" * 64, "audio/ogg"),
    "mp4": (b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64, "audio/mp4"),
    "wav": (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64, "audio/wav"),
    "mp3": (b"ID3\x03\x00" + b"\x00" * 64, "audio/mpeg"),
}


def make_upload(data: bytes, content_type: str, filename: str = "answer.webm") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename, headers=Headers({"content-type": content_type}))


@pytest.mark.parametrize("fmt", sorted(SAMPLES))
def test_detect_audio_format(fmt):
    assert detect_audio_format(SAMPLES[fmt][0]) == fmt


def test_detect_audio_format_rejects_non_audio():
    assert detect_audio_format(b"<?php echo 1; ?>") is None
    assert detect_audio_format(b"") is None


def test_mp3_frame_sync_without_id3_tag_is_detected():
    assert detect_audio_format(b"\xff\xfb\x90\x00" + b"\x00" * 20) == "mp3"


def test_normalize_content_type_strips_parameters_and_case():
    assert audio_intake.normalize_content_type("Audio/WebM;codecs=opus") == "audio/webm"
    assert audio_intake.normalize_content_type(None) == ""


@pytest.mark.parametrize("fmt", sorted(SAMPLES))
def test_valid_upload_is_saved_under_server_generated_name(tmp_path, fmt):
    data, ctype = SAMPLES[fmt]
    response_id = uuid.uuid4()
    saved = save_upload(make_upload(data, ctype, filename="../../evil name.exe"), response_id, str(tmp_path), 1024 * 1024)
    assert saved.path.name == f"{response_id}.{fmt}"
    assert saved.path.read_bytes() == data
    assert saved.size_bytes == len(data)
    assert [p.name for p in tmp_path.iterdir()] == [saved.path.name]  # nothing else, no .part left


def test_codec_parameter_in_content_type_is_accepted(tmp_path):
    data, _ = SAMPLES["webm"]
    saved = save_upload(make_upload(data, "audio/webm;codecs=opus"), uuid.uuid4(), str(tmp_path), 1024)
    assert saved.content_type == "audio/webm"


def test_unsupported_content_type_is_rejected_with_415(tmp_path):
    with pytest.raises(AudioValidationError) as exc:
        save_upload(make_upload(b"hello", "text/plain"), uuid.uuid4(), str(tmp_path), 1024)
    assert exc.value.status_code == 415
    assert not list(tmp_path.iterdir())


def test_content_that_does_not_match_declared_type_is_rejected(tmp_path):
    with pytest.raises(AudioValidationError) as exc:
        save_upload(make_upload(b"<?php system($_GET['c']); ?>", "audio/webm"), uuid.uuid4(), str(tmp_path), 1024)
    assert exc.value.status_code == 415
    # A real WAV file declared as webm is also a mismatch.
    with pytest.raises(AudioValidationError):
        save_upload(make_upload(SAMPLES["wav"][0], "audio/webm"), uuid.uuid4(), str(tmp_path), 1024)
    assert not list(tmp_path.iterdir())


def test_empty_upload_is_rejected_with_400(tmp_path):
    with pytest.raises(AudioValidationError) as exc:
        save_upload(make_upload(b"", "audio/webm"), uuid.uuid4(), str(tmp_path), 1024)
    assert exc.value.status_code == 400


def test_oversized_upload_is_rejected_with_413_and_leaves_no_file(tmp_path):
    data = SAMPLES["webm"][0] + b"\x00" * 5000
    with pytest.raises(AudioValidationError) as exc:
        save_upload(make_upload(data, "audio/webm"), uuid.uuid4(), str(tmp_path), 1000)
    assert exc.value.status_code == 413
    assert not list(tmp_path.iterdir())


def test_upload_exactly_at_limit_is_accepted(tmp_path):
    data = SAMPLES["webm"][0]
    saved = save_upload(make_upload(data, "audio/webm"), uuid.uuid4(), str(tmp_path), len(data))
    assert saved.size_bytes == len(data)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only")
def test_directory_and_file_permissions_are_private(tmp_path):
    target = tmp_path / "private"
    saved = save_upload(make_upload(*SAMPLES["webm"]), uuid.uuid4(), str(target), 1024)
    assert (target.stat().st_mode & 0o777) == 0o700
    assert (saved.path.stat().st_mode & 0o777) == 0o600


def test_find_and_delete_audio(tmp_path):
    response_id = uuid.uuid4()
    saved = save_upload(make_upload(*SAMPLES["ogg"]), response_id, str(tmp_path), 1024)
    assert audio_intake.find_audio_path(response_id, str(tmp_path)) == saved.path
    audio_intake.delete_audio(response_id, str(tmp_path))
    assert audio_intake.find_audio_path(response_id, str(tmp_path)) is None
    audio_intake.delete_audio(response_id, str(tmp_path))  # deleting twice is harmless


def test_purge_removes_only_stale_audio_files(tmp_path):
    old, fresh, other = tmp_path / f"{uuid.uuid4()}.webm", tmp_path / f"{uuid.uuid4()}.webm", tmp_path / "notes.txt"
    for f in (old, fresh, other):
        f.write_bytes(b"x")
    past = time.time() - 3 * 3600
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert audio_intake.purge_stale_audio(str(tmp_path), max_age_seconds=3600) == 1
    assert not old.exists() and fresh.exists() and other.exists()


def test_purge_on_missing_directory_is_a_noop(tmp_path):
    assert audio_intake.purge_stale_audio(str(tmp_path / "nope"), 60) == 0
