"""FFmpeg helpers: turn the engine's WAV into a Discord-friendly MP3, and make a short clip.

A best-parts mix WAV (~3 min, 44.1 kHz stereo) is ~30 MB — over Discord's 8 MB free upload
limit — so we transcode to MP3 (~3–4 MB) before posting. FFmpeg is required for both this
transcode and voice playback (v8 full build is present on the founder's machine).
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


async def _run(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg(), *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        tail = (err or b"").decode(errors="ignore")[-400:]
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {tail}")


async def to_mp3(src, dest, bitrate: str = "160k") -> Path:
    """Transcode any audio file to MP3 (default 160 kbps — ~3.6 MB for a 3-min mix, under
    Discord's 8 MB free limit, and shareable)."""
    await _run("-y", "-i", str(src), "-codec:a", "libmp3lame", "-b:a", bitrate, str(dest))
    return Path(dest)


async def clip_mp3(src, dest, start: float = 0.0, duration: float = 20.0,
                   bitrate: str = "160k") -> Path:
    """A short shareable clip (default first 20 s) as MP3 — the creator's native unit."""
    await _run("-y", "-ss", str(start), "-t", str(duration), "-i", str(src),
               "-codec:a", "libmp3lame", "-b:a", bitrate, str(dest))
    return Path(dest)
