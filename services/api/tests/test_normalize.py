import subprocess
import wave
from pathlib import Path

import pytest

from app.audio.normalize import AudioError, normalize_audio


def _make_tone(path: Path) -> None:
    """A 1-second 440 Hz tone at a deliberately non-standard 22050 Hz / mono."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ac", "1", "-ar", "22050", str(path)],
        check=True, capture_output=True,
    )


def test_normalize_produces_standard_wav(tmp_path):
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.wav"
    _make_tone(src)

    normalize_audio(src, dst)

    with wave.open(str(dst), "rb") as w:
        assert w.getframerate() == 44100
        assert w.getnchannels() == 2
        assert w.getsampwidth() == 2  # 16-bit PCM


def test_normalize_rejects_garbage(tmp_path):
    src = tmp_path / "bad.wav"
    dst = tmp_path / "out.wav"
    src.write_bytes(b"not audio at all")

    with pytest.raises(AudioError):
        normalize_audio(src, dst)
