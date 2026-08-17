"""FFmpeg wrapper: clean an arbitrary audio file into a standardized WAV.

Target: 44.1 kHz, stereo, 16-bit PCM, peak-normalized to 0 dBFS. This is the
foundation every later milestone (analysis, stems, mixing) builds on — the
whole pipeline assumes consistent input, so we standardize here at ingest.

The LLM never touches audio; this is pure deterministic DSP via FFmpeg.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class AudioError(Exception):
    """Raised when a file cannot be decoded or normalized as audio."""


# Generous ceiling: a normal song's two-pass normalize finishes in seconds.
# The timeout only exists to kill a pathological/malicious file that would
# otherwise hang a worker forever (a denial-of-service with no attacker skill).
_FFMPEG_TIMEOUT_SEC = 120


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired:
        raise AudioError("audio processing timed out")


def probe_seconds(src: Path) -> float:
    """How long this file claims to be, WITHOUT decoding it. 0.0 if it cannot be read.

    Exists because checking a duration limit after `normalize_audio` is far too late: a 14 MB,
    4-hour, 8 kbps MP3 decodes to a 2.5 GB WAV, so the file is already on disk by the time the
    limit is applied. Measured in the 2026-08-17 security review — one request could take the
    laptop under its free-disk floor, which then wakes the cleaner and costs other people their
    finished mixes. ffprobe reads the container header only, so this is instant and allocates
    nothing.

    The value is the file's OWN claim and a hostile file can lie, so it is a cheap first gate, not
    the last word — `normalize_audio` caps the decode as well.
    """
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", str(src)])
    try:
        return float((p.stdout or "").strip())
    except (TypeError, ValueError):
        return 0.0


def _measure_peak_db(src: Path) -> float:
    """Pass 1 — detect the current peak level so we can lift it to 0 dBFS."""
    p = _run(["ffmpeg", "-i", str(src), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr)
    if p.returncode != 0 or m is None:
        raise AudioError(f"could not analyze audio: {p.stderr[-300:]}")
    return float(m.group(1))


def normalize_audio(src: Path, dst: Path, max_seconds: float | None = None) -> None:
    """Decode ``src`` and write a standardized, peak-normalized WAV to ``dst``.

    Raises ``AudioError`` if the input is not decodable audio.

    `max_seconds` caps the DECODE, so a file that lies about its length in the container header
    still cannot expand without bound on disk. Defaults to None (no cap) so the operator ingest
    path, which takes files the founder chose, is unchanged.
    """
    peak_db = _measure_peak_db(src)
    gain = -peak_db  # bring the loudest sample to 0 dBFS

    # Pass 2 — apply the gain and standardize format.
    limit = ["-t", str(float(max_seconds))] if max_seconds else []
    p = _run([
        "ffmpeg", "-y", "-i", str(src), *limit,
        "-af", f"volume={gain}dB",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
        str(dst),
    ])
    if p.returncode != 0 or not dst.exists():
        raise AudioError(f"could not normalize audio: {p.stderr[-300:]}")
