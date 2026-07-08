"""The referee: enforce the hard rules on the plan AND on the finished audio.

This is the quality guardrail (a dangerous surface — never remove it). The plan is
checked before we spend time rendering; the real rendered WAV is checked before it
is ever served, because analysis can be wrong and a plan that reads fine can still
produce a broken sound (DJ Handbook Part 9: verify at the moment of firing).

The hard rules:
  R1 (single lead vocal): only Song 2's vocal is ever added (Song 1's is removed), so
     the source is single by construction — but an M4 arrangement places it in several
     spots, so we assert those placements never OVERLAP in time (never two voices at
     once). R2 (single bassline) holds by construction (only Song 1's bass).
  R3  every vocal entry lands on a downbeat of Song 1 (never mid-bar).
  B3  the tempo stretch stays inside the safe band (no warble).
  R6  the finished audio is neither silent/near-silent nor clipping.
  R7  a beat-locked (warped) placement re-locks cleanly: every per-bar stretch stays in
      the safe band, and each bar boundary lands on a Song 1 downbeat (no mid-bar drift).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from app.models import MixPlan, TrackAnalysis
from app.planner.fence import (HOUSE_SLOW_MAX, HOUSE_SPEED_MAX, LEAD_XFADE_SECS,
                               SAFE_STRETCH_HI, SAFE_STRETCH_LO, placement_end, retimed_analysis)

# A sample magnitude at or above this counts as clipping (square-wave distortion).
CLIP_CEILING = 0.999
# How close to a downbeat the vocal entry must land to count as "on the beat".
BEAT_TOLERANCE_SECS = 0.06
# "Not silent" means genuinely audible, not just "one non-zero sample": at least
# this fraction of samples must clear the audible floor. Catches a mix that is
# mostly silence with a stray blip (exact-zero-peak alone would wave that through),
# while sitting far below any real mix (whose audible fraction is ~0.9+).
AUDIBLE_FLOOR = 0.01
MIN_AUDIBLE_FRACTION = 0.02
# Effects the engine actually implements. A plan asking for anything else (e.g. a typo like
# "sweep-in") would silently render no effect — for a product whose worst outcome is a
# worse-sounding mix, we fail it loudly instead of shipping it quietly.
_KNOWN_FX = {"sweep_in"}


class ValidationError(Exception):
    """Raised when a plan or a render breaks a hard rule; carries every violation."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


def _on_a_downbeat(t: float, downbeats: list[float]) -> bool:
    if not downbeats:  # can't verify without a grid — don't fail on missing data
        return True
    return any(abs(t - d) <= BEAT_TOLERANCE_SECS for d in downbeats)


def _placements_of(plan: MixPlan) -> list:
    """The plan's vocal placements — or the scalar anchor/vocal_src as a one-element
    arrangement, so a legacy (M3) single-placement plan still validates."""
    if plan.placements:
        return list(plan.placements)
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src, "warp": []})()]


def _warp_violations(p, downbeats: list[float]) -> list[str]:
    """R7: a warped placement must re-lock cleanly — every per-bar stretch inside the safe
    band (no warble), and every full-bar boundary on a Song 1 downbeat (the vocal's own end,
    the last boundary, may fall mid-bar). Empty warp => nothing to check (legacy path)."""
    warp = getattr(p, "warp", None)
    if not warp:
        return []
    out: list[str] = []
    cum = p.anchor
    for i, (s0, s1, out_secs) in enumerate(warp):
        if out_secs <= 0 or not (SAFE_STRETCH_LO - 1e-6 <= (s1 - s0) / out_secs <= SAFE_STRETCH_HI + 1e-6):
            msg = "a beat-lock bar is outside the safe stretch band (R7)"
            if msg not in out:
                out.append(msg)
        cum += out_secs
        if i < len(warp) - 1 and not _on_a_downbeat(cum, downbeats):  # interior boundary must lock
            msg = "a beat-lock bar boundary drifted off Song 1's grid (R7)"
            if msg not in out:
                out.append(msg)
    return out


def validate_plan(plan: MixPlan, a1: TrackAnalysis, a2: TrackAnalysis) -> list[str]:
    """Return the list of hard-rule violations in the plan (empty == clean)."""
    violations: list[str] = []
    # Movable master: when Song 1's bed is stretched to a shared tempo, the house stretch must be
    # inside its protected band, the master tempo must be self-consistent with Song 1's real tempo
    # (so the referee stays an INDEPENDENT check, not an echo of the plan it judges), and every
    # on-beat/warp check below must run against the RETIMED grid the audio actually plays at. We
    # engage on the SAME 1e-6 threshold the planner and engine use, so the three can never disagree
    # about whether the grid moved (an off-beat mix the referee couldn't see). bed_stretch == 1.0
    # (every existing plan) skips this whole block -> validated exactly as before.
    bed_stretch = getattr(plan, "bed_stretch", 1.0) or 1.0
    if abs(bed_stretch - 1.0) >= 1e-6:
        if not (1.0 - HOUSE_SLOW_MAX - 1e-6 <= bed_stretch <= 1.0 + HOUSE_SPEED_MAX + 1e-6):
            violations.append("the house tempo stretch is outside the safe band (B3)")
        if a1.bpm and abs(plan.master_bpm - a1.bpm * bed_stretch) > 0.1:
            violations.append("the master tempo is inconsistent with the house stretch (B3)")
        a1 = retimed_analysis(a1, plan.master_bpm)
    if not SAFE_STRETCH_LO <= plan.vocal_stretch <= SAFE_STRETCH_HI:
        violations.append("tempo stretch is outside the safe band (B3)")

    ordered = sorted(_placements_of(plan), key=lambda p: p.anchor)
    for p in ordered:
        if not _on_a_downbeat(p.anchor, a1.downbeats):
            violations.append("a vocal entry is not on a downbeat of Song 1 (R3)")
        if p.vocal_src[1] <= p.vocal_src[0]:
            violations.append("a vocal slice is empty")
        fx = getattr(p, "fx", None)
        if fx is not None and fx not in _KNOWN_FX:
            violations.append(f"unknown effect '{fx}' (the engine would silently do nothing)")
        violations.extend(_warp_violations(p, a1.downbeats))  # R7: beat-lock re-locks cleanly
    for a, b in zip(ordered, ordered[1:]):  # R1: one vocal at a time — no S2↔S2 overlap
        # Uses the shared rendered-length math (warp-aware source/stretch), so the referee
        # and the driver measure a vocal's real end identically and can never drift apart.
        if b.anchor < placement_end(a.anchor, a.vocal_src, plan.vocal_stretch, getattr(a, "warp", None)) - 1e-6:
            violations.append("two vocal placements overlap (R1)")

    # R1 across both songs: Song 1's own vocal and Song 2's must not play as two full leads at
    # once. A short hand-off overlap is allowed — Song 1's tail may run at most LEAD_XFADE_SECS
    # past Song 2's entry, just long enough for its own natural phrase-end decay to ring as Song 2
    # enters (the recording's own tail, a DJ blend). Any other overlap (Song 1 starting inside
    # Song 2's lead, or running longer) is two full voices — rejected.
    for s, e in getattr(plan, "s1_vocal_regions", []):
        if e <= s:
            violations.append("a Song 1 vocal region is empty")
            continue
        for p in ordered:
            p_end = placement_end(p.anchor, p.vocal_src, plan.vocal_stretch, getattr(p, "warp", None))
            if s < p_end - 1e-6 and e > p.anchor + 1e-6:  # the spans overlap at all
                is_crossfade = s <= p.anchor + 1e-6 and e <= p.anchor + LEAD_XFADE_SECS + 1e-6
                if not is_crossfade:  # a fade-out tail into the entry is fine; anything else is two leads
                    violations.append("Song 1 and Song 2 vocals overlap beyond a crossfade (R1)")
                    break
    return violations


def validate_render(wav_path: Path) -> list[str]:
    """Return the list of hard-rule violations in the finished audio (empty == clean)."""
    violations: list[str] = []
    y, _sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if y.size == 0:
        return ["render is empty (R6)"]
    peak = float(np.max(np.abs(y)))
    if peak >= CLIP_CEILING:
        violations.append(f"render clips at peak {peak:.3f} (R6)")
    audible = float(np.mean(np.abs(y) > AUDIBLE_FLOOR))
    if audible < MIN_AUDIBLE_FRACTION:
        violations.append(f"render is silent or near-silent ({audible:.1%} audible) (R6)")
    return violations


def assert_plan(plan: MixPlan, a1: TrackAnalysis, a2: TrackAnalysis) -> None:
    v = validate_plan(plan, a1, a2)
    if v:
        raise ValidationError(v)


def assert_render(wav_path: Path) -> None:
    v = validate_render(wav_path)
    if v:
        raise ValidationError(v)
