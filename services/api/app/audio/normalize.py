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


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _measure_peak_db(src: Path) -> float:
    """Pass 1 — detect the current peak level so we can lift it to 0 dBFS."""
    p = _run(["ffmpeg", "-i", str(src), "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr)
    if p.returncode != 0 or m is None:
        raise AudioError(f"could not analyze audio: {p.stderr[-300:]}")
    return float(m.group(1))


def normalize_audio(src: Path, dst: Path) -> None:
    """Decode ``src`` and write a standardized, peak-normalized WAV to ``dst``.

    Raises ``AudioError`` if the input is not decodable audio.
    """
    peak_db = _measure_peak_db(src)
    gain = -peak_db  # bring the loudest sample to 0 dBFS

    # Pass 2 — apply the gain and standardize format.
    p = _run([
        "ffmpeg", "-y", "-i", str(src),
        "-af", f"volume={gain}dB",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
        str(dst),
    ])
    if p.returncode != 0 or not dst.exists():
        raise AudioError(f"could not normalize audio: {p.stderr[-300:]}")
