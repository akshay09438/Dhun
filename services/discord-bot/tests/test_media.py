"""media (ffmpeg) tests — skipped automatically if ffmpeg isn't on PATH."""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import media  # noqa: E402

pytestmark = pytest.mark.skipif(not media.ffmpeg_available(), reason="ffmpeg not installed")


def _silent_wav(path: Path, seconds: float = 1.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=44100:cl=stereo", "-t", str(seconds), str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_to_mp3_produces_a_nonempty_file():
    with tempfile.TemporaryDirectory() as d:
        wav, mp3 = Path(d) / "in.wav", Path(d) / "out.mp3"
        _silent_wav(wav)
        asyncio.run(media.to_mp3(wav, mp3))
        assert mp3.exists() and mp3.stat().st_size > 0


def test_clip_mp3_is_shorter_than_source():
    with tempfile.TemporaryDirectory() as d:
        wav, mp3 = Path(d) / "in.wav", Path(d) / "clip.mp3"
        _silent_wav(wav, seconds=4.0)
        asyncio.run(media.clip_mp3(wav, mp3, start=0.0, duration=1.0))
        assert mp3.exists() and mp3.stat().st_size > 0
