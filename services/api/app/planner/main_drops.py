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
    # Innerbloom (RÜFÜS DU SOL) — 6:17, where its own lyrics start: the moment Song 2 rides in with
    # them (paired with its vocal-entry floor in vocal_windows.py, same time). Marked because the hook
    # must land HERE by the founder's rule, not on whichever anchor happens to be loudest — energy
    # detection ranks 7:05 above 6:17, so without this mark the signature line drifts off the hand-over
    # (measured: the hook slid to 7:05 and 6:17 got an 8s scrap). 2026-07-16.
    "2471e18e1eb820114c0782501babac43b6e5b52c06254da4c1fe0d9e8369c406": [377.0],
    # --- Three vocal-heavy EDM beats, founder-marked by ear 2026-08-08 (scripts/mark_drops.html).
    #     energy_drops OVER-FIRES on these (measured 2026-08-08: precision ~36%, 14 found vs 6 real —
    #     Wake Me Up 7-for-2, Lean On 6-for-2), so the vocal could sync to a false drop. These ear-marks
    #     REPLACE detection with the real drops. Recall was already 83% (the real ones ARE found, ~0.15
    #     bars off), so the marks mostly strip the false positives. ---
    # Wake Me Up (Avicii) — the two real drops.
    "e6722353c4251a3f9af0a76ab620b22f61fa6e385846ae67073debafa6acf1ad": [38.31, 93.09],
    # Faded (Alan Walker).
    "f61ea8edc6c56a0a1da0de64d26768618e6007262fbca7738d8571ccfa92c7fa": [54.65, 76.36],
    # Lean On (Major Lazer & DJ Snake).
    "ed2c86b75c81961842d7ea6509d0d962efd1798c49e45bed01395db0d49bcc46": [29.42, 48.97],
    # Closer (The Chainsmokers ft. Halsey) — founder-marked drops 0:31 and 1:11 (2026-08-08).
    "3f260b5cadb5a20ca475f50553f4d8512ed2764ba9f4d7988f9c1e0111d25f4e": [31.0, 71.0],
    # --- Two new beats, founder-marked by ear (scripts/mark_drops.html), wired 2026-08-10. ---
    # Hey Brother (Avicii) — founder-marked drop 0:35.
    "40350cd8721eb38d2043d8c0b8c6210539f3b4440931f7a1745459a8bb37ec1c": [34.99],
    # Silence — founder-marked drop 1:08.
    "9bf2835f9efdc58f4e3a83b95e8f1d6180ed10de0f49d183fa3690e15dec99e1": [67.62],
}


def main_drops_for(song_id: str) -> list[float]:
    """Hand-marked main-drop times (seconds, native timeline) for this beat, or [] to auto-detect."""
    return MAIN_DROPS.get(song_id, [])
