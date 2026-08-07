"""Beat-grid HEALTH check — 'are the beat sensors reading cleanly?' (founder rule 2026-08-07:
the beat detection must be on point, or the on-beat rules can't hold).

Everything downstream (the per-bar beat-lock, every on-beat move) trusts Song 1's downbeats. If the
detector mis-fired — an irregular grid, downbeats that don't match the detected BPM — the lock snaps
to the wrong places and the mix drifts, no matter how good the rules are. This module measures the
grid's INTERNAL consistency (pure arithmetic on the cached analysis; no re-analysis) so a bad grid is
VISIBLE (logged per mix) and can lower confidence to trigger the existing fallback ladder.

Pure + dependency-free so it is trivially testable and safe to call on every render.
"""
from __future__ import annotations

from statistics import median, pstdev

_CV_TOL = 0.25  # coefficient-of-variation at which regularity hits 0 (a real 4/4 grid has CV well under 0.05)


def downbeat_regularity(downbeats: list[float]) -> float:
    """How evenly spaced the downbeats are, in [0, 1] (1 = perfectly regular). A real 4/4 grid has
    near-constant bar spacing; a detector that dropped/added beats spreads the gaps out. Score uses the
    coefficient of variation (std/mean of gaps) — outlier-sensitive, so a few bad bars DO show — mapped
    1 - CV/_CV_TOL and clamped. <3 downbeats -> 0.0."""
    if not downbeats or len(downbeats) < 3:
        return 0.0
    gaps = [b - a for a, b in zip(downbeats, downbeats[1:]) if b > a]
    if len(gaps) < 2:
        return 0.0
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return 0.0
    cv = pstdev(gaps) / mean
    return max(0.0, min(1.0, 1.0 - cv / _CV_TOL))


def bpm_grid_agreement(bpm: float | None, downbeats: list[float]) -> float:
    """Does the downbeat spacing agree with the detected BPM? A 4/4 bar at `bpm` lasts 4*60/bpm secs;
    the median downbeat gap should match. Returns agreement in [0, 1] (1 = exact). Handles the common
    octave/half-bar confusions (2 or 8 beats per 'bar') by taking the best-matching multiple, so a real
    grid read at half/double bar length still scores high — only a genuinely inconsistent grid scores low."""
    if not bpm or bpm <= 0 or len(downbeats) < 3:
        return 0.0
    gaps = [b - a for a, b in zip(downbeats, downbeats[1:]) if b > a]
    if not gaps:
        return 0.0
    med = median(gaps)
    beat = 60.0 / bpm
    best = 0.0
    for beats_per_bar in (2, 4, 8):                 # tolerate half-/double-bar grid conventions
        expected = beats_per_bar * beat
        if expected <= 0:
            continue
        ratio = min(med, expected) / max(med, expected)
        best = max(best, ratio)
    return max(0.0, min(1.0, best))


def grid_health(bpm: float | None, downbeats: list[float]) -> dict:
    """Combined beat-sensor health for one track. Returns {regularity, bpm_agreement, health, ok}.
    `health` is the min of the two (a grid is only as trustworthy as its weakest signal); `ok` is a
    conservative pass at >= 0.75. Callers LOG this per mix and may lower confidence when not ok, so a
    mis-detected grid engages the fallback ladder instead of silently shipping an off-beat mix."""
    reg = downbeat_regularity(downbeats)
    agr = bpm_grid_agreement(bpm, downbeats)
    health = min(reg, agr)
    return {"regularity": round(reg, 3), "bpm_agreement": round(agr, 3),
            "health": round(health, 3), "ok": health >= 0.8}
