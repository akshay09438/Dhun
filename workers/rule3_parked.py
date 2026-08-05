"""PARKED for Rule 3 (chop-and-repeat) — NOT used by Rule 4, NOT imported by the render path.

WHY THIS FILE EXISTS
--------------------
`punchy_bar` was built during the Rule-4 "phrase-throw" experiment (2026-08-05), which re-fired a
downbeat-aligned bar of the vocal across a gap. That re-fire is CHOP-AND-REPEAT — it belongs to Rule 3,
not Rule 4 — so it was cut from Rule 4. But the helper itself is genuinely useful and carries a
HARD-WON fix, so it is parked here as a real, findable helper rather than left only in git history.

THE HARD-WON FIX (do not lose it)
---------------------------------
`punchy_bar` returns None when the candidate fragment is below the VOICED floor — i.e. it refuses to
re-fire a BREATH. This came from the "Father Ocean 3:56" defect: a raw onset grabbed a breath and
re-firing it killed the drop. Any future chop-and-repeat (Rule 3) MUST keep this breath check.

The constants below MIRROR workers/render.py (SR, the 8 ms edge fade, the 0.08 voiced floor) so this
file is self-contained and readable on its own. When Rule 3 is built, re-integrate from here.
"""

from __future__ import annotations

import numpy as np

SR = 44_100          # mirrors workers.render.SR
_FADE_MS = 8.0       # mirrors workers.render._FADE_MS — edge fade that kills entry/exit clicks
VOICED_FLOOR = 0.08  # mirrors the Rule-4 detector's voiced floor: RMS below this fraction of peak = a BREATH


def _edge_fade(y: np.ndarray) -> np.ndarray:
    """Fade the first/last `_FADE_MS` so a spliced fragment starts and ends click-free (mirrors render)."""
    k = min(int(SR * _FADE_MS / 1000), len(y) // 2)
    if k > 0:
        ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
        y[:k] *= ramp
        y[-k:] *= ramp[::-1]
    return y


def punchy_bar(voc: np.ndarray, before_sample: int, bar_samples: float) -> np.ndarray | None:
    """The downbeat-aligned bar ending at `before_sample`, to RE-FIRE across a gap (Rule 3, chop-and-
    repeat) — but ONLY if it is VOICED. A fragment whose RMS is below `VOICED_FLOOR` of the vocal's peak
    is a breath / near-silence, so return None (no re-fire). THIS BREATH CHECK IS THE FIX: never re-fire
    a breath (the Father Ocean 3:56 defect). Returns an edge-faded copy of the bar, or None."""
    b = int(bar_samples)
    start = max(0, before_sample - b)
    frag = voc[start:before_sample]
    if len(frag) == 0:
        return None
    peak = float(np.max(np.abs(voc))) if voc.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(frag)))) if frag.size else 0.0
    if peak <= 0.0 or rms < peak * VOICED_FLOOR:
        return None
    return _edge_fade(frag.copy())
