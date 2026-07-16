"""Per-song HAND-MARKED main drop(s) — the moment the vocal's signature line should land on.

The planner normally finds a beat's drop from its energy curve (fence.energy_drops): a downbeat
where loudness jumps up. That works for house/EDM, but some beats have no such energy jump the
detector can see — e.g. a Drum & Bass remix whose energy is fairly flat, so NO drop is found and the
vocal just spreads evenly instead of landing on the real drop (founder ear-report, 2026-07-15).

For those, we mark the main drop BY EAR here, keyed by the beat's content id, exactly like the hooks
(app/planner/hooks.py). When a beat is listed, its marked drop REPLACES energy detection: it becomes
THE drop the arrangement syncs to, so Song 2's hook lands right on it. Times are in SECONDS on the
song's own (native) timeline; the planner snaps each to the nearest downbeat and re-times it onto the
(possibly tempo-shifted) planning grid. A beat NOT listed keeps automatic energy-drop detection.
"""

from __future__ import annotations

MAIN_DROPS: dict[str, list[float]] = {
    # Merrygo beat (trimmed) — a D&B remix of Khuda Jaane; flat energy gave the detector no drop.
    # Founder-marked main drop at 0:40 (the drop section runs 0:40-1:03). 2026-07-15.
    "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480": [40.0],
}


def main_drops_for(song_id: str) -> list[float]:
    """Hand-marked main-drop times (seconds, native timeline) for this beat, or [] to auto-detect."""
    return MAIN_DROPS.get(song_id, [])
