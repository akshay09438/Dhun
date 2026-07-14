"""Pin the FFmpeg build the golden-file test was measured against.

The golden-file byte-identity guarantee (`tests/test_render.py`) rests on FFmpeg producing
bit-identical output. Different FFmpeg versions / build flags / platforms can produce subtly
different audio, which would break the golden gate with NO code change. This records the pinned
version and lets a test fail loudly on a mismatch — so a binary drift surfaces as itself, not
misread as a code regression.

The full build string of the pinned binary is recorded in `docs/ffmpeg.md`.
"""
from __future__ import annotations

import subprocess

# The FFmpeg the golden hash (test_render.py::_GOLDEN_ENABLED_FALSE) was captured against.
# Bump this ONLY together with a deliberate re-capture of the golden hash on the new binary.
PINNED_FFMPEG_VERSION = "8.1.1"


def ffmpeg_version_line() -> str:
    """The first line of `ffmpeg -version` (e.g. 'ffmpeg version 8.1.1-full_build-...'), or '' if
    ffmpeg is unavailable."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-version"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.splitlines()[0].strip() if out.stdout else ""
    except Exception:
        return ""


def matches_pinned_version() -> bool:
    """True iff the running ffmpeg reports the pinned version."""
    return f"ffmpeg version {PINNED_FFMPEG_VERSION}" in ffmpeg_version_line()
