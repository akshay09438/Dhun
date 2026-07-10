"""Standalone level/quality guards for the vocal chain — Phase 0 referee rules P2 (pre-master ceiling)
and the crest-factor mush guard.

WHY THIS IS ITS OWN MODULE (not a function inside render.py): a referee's whole value is that it
re-derives independently rather than being an assertion buried in the code it polices. These guards
live here so that when the chain in render.py changes, the guard does NOT change with it silently.
The dependency is ONE-WAY: render.py imports and calls this; this NEVER imports render.py. It is tested
against synthetic signals with KNOWN answers (a pure sine, a clipped square, noise, silence), so its
correctness does not depend on the render path at all.

P1/P3/P4/P5 are PLAN checks and live in services/api/app/planner/validate.py; P2 and the crest guard
need the intermediate audio (which only the render has), so they are enforced here, render-side.
"""

from __future__ import annotations

import numpy as np

# P2 — relative pre-master peak-gain ceiling. The master peak-normalizes + hard-clips, so the OUTPUT
# can never clip; but it would faithfully normalize a vocal blown up by over-EQ / over-drive. This
# catches the chain inflating the level.
#
# ⚠️ DEVIATION FROM THE ORIGINAL BRIEF (accepted by the founder): the brief specified an ABSOLUTE
# ceiling ("no stage output > -3 dBFS pre-master"). That is incompatible with our signal levels —
# ingest normalizes to 0 dBFS and separated vocal stems sit near 0 dBFS (measured peak ~1.14), so an
# absolute ceiling rejects every real mix. A RELATIVE peak-gain guard is what the brief actually meant.
P2_MAX_GAIN_DB = 3.0
_P2_MAX_GAIN = 10.0 ** (P2_MAX_GAIN_DB / 20.0)

# Crest-factor (peak/RMS) MUSH guard. tanh saturation is a compressor: drive a signal hard and its
# PEAK squashes toward +-1 while RMS climbs, so a peak guard (P2) is structurally BLIND to mush — a
# destroyed vocal can have a LOWER peak than a clean one. Crest factor collapses under distortion —
# that is the signature. This is self-calibrating as a DELTA: the chain may not collapse the crest
# factor below CREST_MIN_RATIO x the input's, so there is no absolute number to guess.
#
# THRESHOLD found empirically (2026-07-10, real Der Lagi vocal through the full chain):
#   input crest factor 5.52 (clean).
#   LEGAL processing (every dial in P3 range, saturate_wet<=0.5): output crest ratio 0.83-0.95.
#   MUSH (distortion beyond the caps): tanh drive 8 -> 0.37; drive 16 -> 0.31; hard-clip square -> 0.26.
# The cliff is a WIDE gap (0.5 .. 0.83). 0.60 sits centered in it: clears all legal processing with
# margin, catches all measured mush with margin. Within the P3 caps this guard cannot fire; it is
# defense-in-depth against a future dial/stage or a bug that pushes distortion past the caps.
CREST_MIN_RATIO = 0.60


def crest_factor(y: np.ndarray) -> float:
    """peak / RMS of a signal (mono or stereo). ~1.41 for a pure sine, -> 1.0 for a full square wave,
    high for a spiky/clean signal. Distortion collapses it. inf for silence (no RMS)."""
    a = np.abs(y)
    peak = float(a.max()) if a.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(y.astype(np.float64))))) if y.size else 0.0
    return peak / rms if rms > 0.0 else float("inf")


def check_vocal_chain_output(before: np.ndarray, after: np.ndarray) -> str | None:
    """Return a plain-language reason the vocal-chain OUTPUT fails a quality guard, or None if it
    passes. Called by the render AFTER the chain runs on a placement, BEFORE the master stage.

    P2 (peak-gain): the chain must not inflate the peak by more than P2_MAX_GAIN_DB.
    Crest (mush): the chain must not collapse the crest factor below CREST_MIN_RATIO x the input's."""
    pk_in = float(np.max(np.abs(before))) if before.size else 0.0
    pk_out = float(np.max(np.abs(after))) if after.size else 0.0
    if pk_in > 0.0 and pk_out > pk_in * _P2_MAX_GAIN:
        return (f"vocal chain raised the peak {20.0 * np.log10(pk_out / pk_in):.1f} dB "
                f"(> {P2_MAX_GAIN_DB:.0f} dB, P2) — over-processed; the master would normalize the level up")
    cf_in = crest_factor(before)
    cf_out = crest_factor(after)
    if np.isfinite(cf_in) and cf_in > 0.0 and cf_out < cf_in * CREST_MIN_RATIO:
        return (f"vocal chain collapsed the crest factor {cf_in:.2f} -> {cf_out:.2f} "
                f"(< {CREST_MIN_RATIO:.2f}x, distortion/mush) — the master would faithfully normalize the mush")
    return None
