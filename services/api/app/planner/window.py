"""Good-parts window: pick the beat song's best ~90s stretch (the run-up into its main
drop) and crop the analysis grid to it, so the existing arrangement engine runs on a tight
window instead of the whole track. Pure arithmetic over TrackAnalysis — no AI, no audio.
Mirrors fence.retimed_analysis: everything here is a testable copy-and-rescale of the grid.
"""
from __future__ import annotations

from app.models import TrackAnalysis
from app.planner import fence

_BARS_PER_PHRASE = 8


def window_analysis(a1: TrackAnalysis, win_start: float, win_end: float) -> TrackAnalysis:
    """Copy `a1` with its grid restricted to [win_start, win_end] and shifted to start at 0.

    Downbeats and the per-bar energy_curve are filtered by the SAME in-window index set so they
    stay aligned (the energy_curve is one value per downbeat-bar). Sections and vocal regions are
    clipped to the window then rebased. bpm/keys/confidences are unchanged.
    """
    lo, hi = win_start - 1e-6, win_end + 1e-6

    def shift(times: list[float]) -> list[float]:
        return [round(t - win_start, 4) for t in times if lo <= t <= hi]

    n_energy = len(a1.energy_curve)
    kept = [i for i, d in enumerate(a1.downbeats)
            if lo <= d <= hi and (n_energy == 0 or i < n_energy)]
    energy = [a1.energy_curve[i] for i in kept] if n_energy else []
    sections = [
        s.model_copy(update={"start": round(max(s.start, win_start) - win_start, 4),
                             "end": round(min(s.end, win_end) - win_start, 4)})
        for s in a1.sections if s.end > win_start and s.start < win_end
    ]
    vocal_regions = [
        (round(max(s, win_start) - win_start, 4), round(min(e, win_end) - win_start, 4))
        for s, e in a1.vocal_regions if e > win_start and s < win_end
    ]
    return a1.model_copy(update={
        "beats": shift(a1.beats),
        "downbeats": [round(a1.downbeats[i] - win_start, 4) for i in kept],
        "phrase_starts": shift(a1.phrase_starts),
        "energy_curve": energy,
        "sections": sections,
        "vocal_regions": vocal_regions,
    })


_TARGET_SECS = 90.0      # the window we aim for
_MIN_SECS = 60.0         # ...flexible down to here
_MAX_SECS = 120.0        # ...and up to here
_TAIL_SECS = 30.0        # beat time AFTER the main drop — long enough for the hook that lands ON the
                         # drop to keep playing OVER the beat (not sing on over silence), plus a resolve
_MIN_RUNUP_SECS = 16.0   # need at least this much build-up before the drop, else no window


def _phrase_energy_at(a1: TrackAnalysis, t: float) -> float:
    """Average energy of the phrase (8 bars) nearest time t; 0 without an energy grid. Used for CUE
    selection (a low-density spot) — the phrase-aligned block is right there."""
    if not (a1.downbeats and a1.energy_curve):
        return 0.0
    idx = min(range(len(a1.downbeats)), key=lambda i: abs(a1.downbeats[i] - t))
    start = (idx // _BARS_PER_PHRASE) * _BARS_PER_PHRASE
    window = a1.energy_curve[start:start + _BARS_PER_PHRASE]
    return sum(window) / len(window) if window else 0.0


def _drop_intensity(a1: TrackAnalysis, t: float) -> float:
    """How hard a drop HITS: the mean energy of the bars AT and AFTER the onset (not the phrase-
    aligned block). A big drop is preceded by a near-silent breakdown; a phrase average that includes
    those quiet run-up bars WRONGLY ranks the most dramatic drops LOW (founder ear-test 2026-07-09:
    Father Ocean's 3:56 main drop, energy ~0.95 at the hit, scored 0.37 by phrase-average because of
    the ~0.05 bars right before it — losing to a flatter 7:20 section). Measuring from the onset
    forward captures the hit itself."""
    if not (a1.downbeats and a1.energy_curve):
        return 0.0
    i = min(range(len(a1.downbeats)), key=lambda k: abs(a1.downbeats[k] - t))
    window = a1.energy_curve[i:i + _BARS_PER_PHRASE]
    return sum(window) / len(window) if window else 0.0


def _snap(anchors: list[float], t: float) -> float:
    """Nearest phrase/downbeat anchor to t (t itself if there are no anchors)."""
    return min(anchors, key=lambda a: abs(a - t)) if anchors else t


def choose_window(a1: TrackAnalysis, drops: list[float], take: int = 1) -> tuple[float, float] | None:
    """The ~90s good-part window anchored on a MAIN drop (a hardest-hitting drop = the payoff).

    Ends a short tail AFTER the drop (snapped to a phrase, clamped to the track). Starts on the best
    CUE POINT: the lowest-density (lowest-energy) phrase boundary that keeps the span in the 60-120s
    band and leaves real run-up before the drop — so the mix eases in where a DJ would (a breakdown/
    quiet spot), not mid-chorus. `take` rotates the window across the strong drops for VARIATION (a
    different valid mix each play). Returns None when there is no drop, no legal cue with run-up, or
    the track is too short — in every None case the caller keeps today's full-track mix.
    """
    if not drops or not a1.beats:
        return None
    track_end = a1.beats[-1]
    # The MAIN drop = how hard it HITS (post-onset intensity, not a phrase average that would bury a
    # big drop under its own quiet run-up). For VARIATION (founder 2026-07-09: never the same mix),
    # rotate by `take` among the genuinely-strong drops (>= 60% of the hardest hit), so each take
    # lands its window on a different real drop — take=1 is the hardest, later takes pick other strong
    # ones. Vocal-slice/cue variety already keys off `take` downstream, so the whole mix varies.
    ranked = sorted(drops, key=lambda d: _drop_intensity(a1, d), reverse=True)
    top = _drop_intensity(a1, ranked[0])
    strong = [d for d in ranked if _drop_intensity(a1, d) >= 0.6 * top] or ranked[:1]
    main = strong[(take - 1) % len(strong)]
    phrases = a1.phrase_starts or a1.downbeats or a1.beats

    win_end = min(track_end, _snap(phrases, main + _TAIL_SECS))
    if win_end <= main:                                   # drop at the very end -> tiny tail, no snap
        win_end = min(track_end, main + _TAIL_SECS)

    # Start on the best CUE POINT: among the phrase boundaries that keep the span in the 60-120s
    # band AND leave real run-up before the drop, pick the LOWEST-density (lowest-energy) one — a
    # breakdown/quiet spot, where a DJ starts bringing a track in, never mid-chorus. Ties break
    # toward a ~90s window. (Founder craft note 2026-07-09: cue/switch points sit on phrase
    # boundaries at points of lower musical density, e.g. right as a breakdown starts.)
    earliest = max(0.0, win_end - _MAX_SECS)
    latest = min(win_end - _MIN_SECS, main - _MIN_RUNUP_SECS)
    if latest < earliest:                                 # no legal start with run-up -> fall back
        return None
    cues = [p for p in phrases if earliest - 1e-6 <= p <= latest + 1e-6]
    if not cues:                                          # no phrase boundary in band -> fall back
        return None
    win_start = min(cues, key=lambda p: (round(_phrase_energy_at(a1, p), 3),
                                         abs((win_end - p) - _TARGET_SECS)))
    return (round(win_start, 3), round(win_end, 3))


def windowed_options(opts: dict, win_start: float, win_end: float) -> dict:
    """Re-derive the arrangement menu on the windowed grid, keeping every Song-2/tempo field.

    The whole downstream engine (plan.build_mix_plan) reads these opts + a1_grid, so recomputing
    just the grid-derived fields on the 0-based windowed grid makes the existing arrangement run
    on the window with no other change.
    """
    a1w = window_analysis(opts["a1_grid"], win_start, win_end)
    need = min(e - s for s, e in opts["vocal_slices"]) * opts["vocal_stretch"]
    anchors = fence.candidate_drops(a1w, need)
    track_end = a1w.beats[-1] if a1w.beats else (max(anchors) + need if anchors else need)
    return {
        **opts,
        "a1_grid": a1w,
        "anchors_ranked": anchors,
        "drops": fence.energy_drops(a1w.energy_curve, a1w.downbeats),
        "track_end": track_end,
        "sections": [(s.start, s.label) for s in a1w.sections],
    }
