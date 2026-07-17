"""Per-song HAND-MARKED main drop(s) — the moment the vocal's signature line should land on.

The planner normally finds a beat's drop from its energy curve (fence.energy_drops): a downbeat
where loudness jumps up. That works for house/EDM, but it is a LOUDNESS detector, so it misses two
kinds of real drop:

  1. **Flat energy — no drop found at all.** A Drum & Bass remix whose energy barely moves, so the
     vocal just spreads evenly instead of landing on the real drop (founder ear-report, 2026-07-15).
  2. **A MELODIC drop — the wrong drop found.** The payoff is a synth swell where the drums drop
     OUT, so energy goes DOWN at the very moment that matters. The detector confidently picks some
     louder-but-lesser spot instead, and the vocal's hook lands there (founder ear-report,
     2026-07-16: "the main part is not coming with the main part of Innerbloom"). This is the
     "main drop != energy argmax" lesson from the earlier best-parts research.

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
    # Innerbloom (RÜFÜS DU SOL) — case 2 above: the payoff is the MELODIC swell at the end of the
    # 5:46-6:02 break, where the drums are OUT. Energy detection therefore never saw it and put the
    # hook at 3:40, so Song 2's signature line never met Innerbloom's (founder ear-report on
    # Innerbloom x Wari Jawa, 2026-07-16). Marked 5:54, matching the founder's own pick recorded in
    # the earlier best-parts research.
    "2471e18e1eb820114c0782501babac43b6e5b52c06254da4c1fe0d9e8369c406": [354.0],
}


def main_drops_for(song_id: str) -> list[float]:
    """Hand-marked main-drop times (seconds, native timeline) for this beat, or [] to auto-detect."""
    return MAIN_DROPS.get(song_id, [])
