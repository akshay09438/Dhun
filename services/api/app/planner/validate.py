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
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from app.models import MixPlan, TrackAnalysis
from app.planner.fence import SAFE_STRETCH_HI, SAFE_STRETCH_LO, placement_end

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
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src})()]


def validate_plan(plan: MixPlan, a1: TrackAnalysis, a2: TrackAnalysis) -> list[str]:
    """Return the list of hard-rule violations in the plan (empty == clean)."""
    violations: list[str] = []
    if not SAFE_STRETCH_LO <= plan.vocal_stretch <= SAFE_STRETCH_HI:
        violations.append("tempo stretch is outside the safe band (B3)")

    ordered = sorted(_placements_of(plan), key=lambda p: p.anchor)
    for p in ordered:
        if not _on_a_downbeat(p.anchor, a1.downbeats):
            violations.append("a vocal entry is not on a downbeat of Song 1 (R3)")
        if p.vocal_src[1] <= p.vocal_src[0]:
            violations.append("a vocal slice is empty")
    for a, b in zip(ordered, ordered[1:]):  # R1: one vocal at a time — no overlap
        # Uses the shared rendered-length math (source / stretch), so the referee and the
        # driver measure a vocal's real end identically and can never drift apart.
        if b.anchor < placement_end(a.anchor, a.vocal_src, plan.vocal_stretch) - 1e-6:
            violations.append("two vocal placements overlap (R1)")
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
