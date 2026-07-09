"""Good-parts window: pick the beat song's best ~90s stretch (the run-up into its main
drop) and crop the analysis grid to it, so the existing arrangement engine runs on a tight
window instead of the whole track. Pure arithmetic over TrackAnalysis — no AI, no audio.
Mirrors fence.retimed_analysis: everything here is a testable copy-and-rescale of the grid.
"""
from __future__ import annotations

from app.models import TrackAnalysis

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

    kept = [i for i, d in enumerate(a1.downbeats) if lo <= d <= hi]
    energy = [a1.energy_curve[i] for i in kept if i < len(a1.energy_curve)]
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
