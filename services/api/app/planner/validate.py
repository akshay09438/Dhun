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
                               SAFE_STRETCH_HI, SAFE_STRETCH_LO, WARP_HI, WARP_LO,
                               placement_end, retimed_analysis)
from app.planner.window import window_analysis

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
# The Song-1 bed stems a Step-3 beat move may ride. An unknown stem would silently do nothing
# in the engine (like an unknown fx), so we fail it loudly.
_BED_STEMS = {"drums", "bass", "other"}
# The audible floor for the never-all-muted guard: at least one bed stem must stay above this at
# every instant, or the plan is rejected. This PLAN-level guard is the primary defense against a
# localized silent hole — validate_render's not-silent check is global (it can't see a brief mid-mix
# hole), so the guard must be sound on its own. It is: same-stem moves can't overlap (rejected in
# _stem_move_violations), so each stem's modelled gain equals the engine's exactly and the muted-span
# math below is exact — no coarse sampling, nothing to slip through.
_ALL_MUTED_EPS = 0.05


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
    """R7: a warped placement must re-lock cleanly — every per-bar stretch inside the WARP grip
    band (WARP_LO..WARP_HI, wider than the global SAFE_STRETCH band: a per-bar re-lock is a
    transient single-bar correction, not a sustained stretch), and every full-bar boundary on a
    Song 1 downbeat (the vocal's own end, the last boundary, may fall mid-bar). Empty warp =>
    nothing to check (legacy path)."""
    warp = getattr(p, "warp", None)
    if not warp:
        return []
    out: list[str] = []
    cum = p.anchor
    for i, (s0, s1, out_secs) in enumerate(warp):
        if out_secs <= 0 or not (WARP_LO - 1e-6 <= (s1 - s0) / out_secs <= WARP_HI + 1e-6):
            msg = "a beat-lock bar is outside the safe stretch band (R7)"
            if msg not in out:
                out.append(msg)
        cum += out_secs
        if i < len(warp) - 1 and not _on_a_downbeat(cum, downbeats):  # interior boundary must lock
            msg = "a beat-lock bar boundary drifted off Song 1's grid (R7)"
            if msg not in out:
                out.append(msg)
    return out


def _muted_spans(moves: list, stem: str) -> list[tuple[float, float]]:
    """The time spans where one bed stem is AT/UNDER the audible floor (_ALL_MUTED_EPS). Its gain is
    1.0 (audible) outside its moves; within a move's linear ramp gain_from→gain_to over [start,end] we
    solve the single point where the ramp crosses the floor. Same-stem moves are guaranteed NOT to
    overlap (the referee rejects overlaps — see _stem_move_violations), so at any instant a stem is
    covered by at most one move: its exact gain IS that move's ramp, and the union of per-move sub-
    spans is the exact muted set. Exact math (no sampling), so a hole between samples can't slip
    through — and, crucially, the guard can never MISS a real hole (only over-flag a measure-zero
    touch)."""
    eps = _ALL_MUTED_EPS
    spans: list[tuple[float, float]] = []
    for m in moves:
        if m.stem != stem or m.end <= m.start:
            continue
        gf, gt = m.gain_from, m.gain_to
        if gf <= eps and gt <= eps:
            spans.append((m.start, m.end))              # muted across the whole ramp
        elif gf > eps and gt > eps:
            continue                                    # this ramp never reaches the floor
        else:                                           # crosses the floor once along the ramp
            t = m.start + (eps - gf) / (gt - gf) * (m.end - m.start)
            spans.append((t, m.end) if gf > eps else (m.start, t))
    return spans


def _all_stems_muted_somewhere(moves: list) -> bool:
    """True if some instant lies in the muted span of ALL THREE bed stems at once (a silent hole).
    Intersects the three stems' exact muted-span unions; touching at a single instant still counts
    (conservative — the guard may false-flag a measure-zero touch but can never MISS a real hole)."""
    d, b, o = (_muted_spans(moves, s) for s in _BED_STEMS)
    for s1, e1 in d:
        for s2, e2 in b:
            lo, hi = max(s1, s2), min(e1, e2)
            if lo <= hi and any(max(lo, s3) <= min(hi, e3) for s3, e3 in o):
                return True
    return False


def _stem_move_violations(moves: list, downbeats: list[float]) -> list[str]:
    """Step 3: every StemMove must ride a real bed stem, land on Song 1's downbeats (R3), have a
    forward window, only duck/return within [0,1] (no boosts → the master can't be pushed to clip),
    and never leave all three bed stems muted at once (no silent hole). Empty moves => no checks =>
    today's behaviour."""
    out: list[str] = []
    if moves and not downbeats:  # a beat move fundamentally needs a grid to lock to; without one the
        out.append("a beat move needs Song 1's downbeat grid to lock to (R3)")  # R3 check is vacuous
    for m in moves:
        if m.stem not in _BED_STEMS:
            out.append(f"a beat move targets an unknown stem '{m.stem}'")
            continue  # nothing else about an unknown stem is meaningful to check
        if m.end <= m.start:
            out.append("a beat move has an empty or backwards window")
        if not (0.0 <= m.gain_from <= 1.0 and 0.0 <= m.gain_to <= 1.0):
            out.append("a beat move gain is outside 0..1 (no boosts in v1)")
        if not _on_a_downbeat(m.start, downbeats) or not _on_a_downbeat(m.end, downbeats):
            out.append("a beat move is not on a downbeat of Song 1 (R3)")
    valid = [m for m in moves if m.stem in _BED_STEMS and m.end > m.start]
    # Two moves on the SAME stem whose windows overlap would MULTIPLY in the engine (its envelope does
    # env *= each ramp), so their combined duck can dip below the floor even when neither alone does —
    # a hole the exact-per-move muted-span math below could not see. Reject overlaps: at most one move
    # per stem at any instant keeps that math exact and the never-all-muted guard sound. Wave 1 never
    # emits overlaps (one bass pull per drop, drops far apart); a plan that does is malformed (two
    # gestures on one stem at once). Runs on ANY plan's moves, so a future/AI plan can't slip past it.
    by_stem: dict[str, list] = {}
    for m in valid:
        by_stem.setdefault(m.stem, []).append(m)
    for stem, ms in by_stem.items():
        ms.sort(key=lambda x: x.start)
        if any(a.end > b.start + 1e-9 for a, b in zip(ms, ms[1:])):
            out.append(f"two beat moves on the same stem ('{stem}') overlap")
    # Never-all-muted (defense-in-depth, exact): if the three bed stems' muted spans share any
    # instant, the bed goes silent there — reject it. Runs on any plan's moves, not just Wave 1's.
    if valid and _all_stems_muted_somewhere(valid):
        out.append("a beat move would mute all of Song 1's bed at once (R6)")
    # de-dupe so N off-beat moves don't repeat the same line N times
    seen: set[str] = set()
    return [v for v in out if not (v in seen or seen.add(v))]


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

    # Good-parts window: the plan's anchors/warp/stem-moves are WINDOW-RELATIVE (0-based from the
    # window start). Re-derive the SAME windowed grid the planner used — crop+rebase from a1 (so the
    # referee stays an INDEPENDENT check, never trusting the plan's own numbers) — and judge on-beat/
    # warp/moves against it. Runs AFTER any bed_stretch retiming, matching the planner's order
    # (retime, then window). window=None -> a1 untouched -> validated exactly as before.
    window = getattr(plan, "window", None)
    if window:
        a1 = window_analysis(a1, *window)

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

    # Step 3: the auto-performed beat moves (bass pull-and-slam, etc.). Checked against the SAME
    # (possibly retimed) a1.downbeats the placements above used, so a move on a movable-master grid
    # is judged on the beats the audio actually plays. Empty stem_moves => no checks => as before.
    violations.extend(_stem_move_violations(getattr(plan, "stem_moves", []), a1.downbeats))
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
