"""PyDub audio preparation. Uses REAL audio files and the real pydub library.
Tests for WebM/OGG/MP4/MP3 additionally need the ffmpeg program and are skipped without it."""

import wave

import pytest

from app.services import audio_processing
from app.services.audio_processing import AudioProcessingError, prepare_for_transcription, validate_source_file
from tests.helpers_audio import FFMPEG_AVAILABLE, ffmpeg_audio, silent_wav_bytes, wav_bytes

needs_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg is not installed")


def prepare(source, tmp_path, **overrides):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    options = {"max_duration_seconds": 60, "min_duration_ms": 300, "target_sample_rate": 16000, **overrides}
    return prepare_for_transcription(source, work, **options), work


def read_wav(path):
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        return handle.getnchannels(), handle.getframerate(), handle.getsampwidth(), handle.getnframes(), frames


def test_stereo_44k_wav_becomes_mono_16k_16bit(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(wav_bytes(1.5, 44100, 2))
    result, work = prepare(source, tmp_path)
    channels, rate, width, frames, _ = read_wav(result.path)
    assert (channels, rate, width) == (1, 16000, 2)
    assert abs(frames / rate - 1.5) < 0.05
    assert result.path == work / "prepared.wav"
    assert (result.source_channels, result.source_sample_rate, result.source_format) == (2, 44100, "wav")
    assert abs(result.duration_seconds - 1.5) < 0.05 and not result.is_silent


def test_low_sample_rate_is_resampled(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(wav_bytes(1.0, 8000, 1))
    result, _ = prepare(source, tmp_path)
    assert read_wav(result.path)[1] == 16000


def test_quiet_audio_is_normalized_towards_full_scale(tmp_path):
    import audioop

    source = tmp_path / "quiet.wav"
    source.write_bytes(wav_bytes(1.0, 16000, 1, amplitude=2000))
    result, _ = prepare(source, tmp_path)
    peak = audioop.max(read_wav(result.path)[4], 2)
    assert peak > 0.8 * 32767


def test_only_the_prepared_file_is_left_in_the_work_folder(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(wav_bytes(1.0))
    _, work = prepare(source, tmp_path)
    assert [p.name for p in work.iterdir()] == ["prepared.wav"]


@pytest.mark.parametrize("data", [silent_wav_bytes(1.0), wav_bytes(1.0, 16000, 1, amplitude=3)])
def test_silent_or_near_silent_audio_is_flagged_and_not_exported(tmp_path, data):
    source = tmp_path / "s.wav"
    source.write_bytes(data)
    result, work = prepare(source, tmp_path)
    assert result.is_silent and result.path is None
    assert list(work.iterdir()) == []


def test_too_short_recording(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(wav_bytes(0.1))
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path)
    assert exc.value.code == "audio_too_short" and exc.value.delete_audio


def test_too_long_recording(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(wav_bytes(3.0, 8000, 1))
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path, max_duration_seconds=2)
    assert exc.value.code == "audio_too_long"


def test_zero_byte_file_is_empty(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(b"")
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path)
    assert exc.value.code == "audio_empty"


def test_text_file_pretending_to_be_audio_is_rejected(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(b"<?php system($_GET['x']); ?> this is not audio at all")
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path)
    assert exc.value.code == "audio_unsupported"


def test_extension_that_does_not_match_the_content_is_rejected(tmp_path):
    source = tmp_path / "a.webm"  # really a WAV
    source.write_bytes(wav_bytes(1.0))
    with pytest.raises(AudioProcessingError) as exc:
        validate_source_file(source)
    assert exc.value.code == "audio_unsupported"


def test_missing_file_keeps_the_retry_option(tmp_path):
    with pytest.raises(AudioProcessingError) as exc:
        prepare(tmp_path / "gone.wav", tmp_path)
    assert exc.value.code == "audio_missing" and exc.value.delete_audio is False


@needs_ffmpeg
def test_corrupted_audio_is_reported_not_crashed(tmp_path):
    source = tmp_path / "bad.wav"
    source.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(range(256)) * 4)
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path)
    assert exc.value.code == "audio_corrupt" and exc.value.delete_audio


@needs_ffmpeg
@pytest.mark.parametrize("fmt", ["webm", "ogg", "mp4", "mp3"])
def test_real_encoded_formats_are_converted(tmp_path, fmt):
    source = ffmpeg_audio(tmp_path / f"answer.{fmt}", seconds=1.5)
    result, _ = prepare(source, tmp_path)
    channels, rate, width, frames, _ = read_wav(result.path)
    assert (channels, rate, width) == (1, 16000, 2)
    assert 1.2 < frames / rate < 1.9
    assert result.source_format == fmt and result.source_channels == 2


@needs_ffmpeg
def test_webm_longer_than_the_limit_is_rejected_without_decoding_everything(tmp_path):
    source = ffmpeg_audio(tmp_path / "long.webm", seconds=6)
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path, max_duration_seconds=2)
    assert exc.value.code == "audio_too_long"


def test_missing_ffmpeg_is_a_server_problem_and_keeps_the_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_processing.shutil, "which", lambda name: None)
    source = tmp_path / "a.webm"
    source.write_bytes(b"\x1a\x45\xdf\xa3" + bytes(64))
    with pytest.raises(AudioProcessingError) as exc:
        prepare(source, tmp_path)
    assert exc.value.code == "decoder_unavailable" and exc.value.delete_audio is False
