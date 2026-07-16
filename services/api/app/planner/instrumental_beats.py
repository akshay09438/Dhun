"""Beats that are actually full VOCAL songs used as instrumentals — use their music ONLY.

Some catalog "beats" are remixes/edits of a vocal song rather than pure instrumentals — e.g.
"Merrygo beat" is a Drum & Bass remix of *Khuda Jaane*, so it carries Khuda Jaane's full vocal.
The arrangement's "both songs trade" flourish (see plan._apply_flourishes) normally weaves Song 1's
OWN vocal into the gaps for contrast — great when Song 1 is a real beat with an occasional vocal
lick, but wrong here: that vocal is a whole second song's lyrics, so it overlaps Song 2's vocal
(founder ear-report, 2026-07-15).

Listing a beat's content id here makes the planner treat it as instrumental-only: it never places
Song 1's own vocal, so only Song 2 sings over the beat. A beat NOT listed keeps today's behaviour
(its own vocal may still trade in). This does NOT touch the audio stems — separation bleed, if any,
is a separate concern; this only stops the planner from deliberately placing Song 1's vocal.
"""

from __future__ import annotations

INSTRUMENTAL_ONLY_BEATS: frozenset[str] = frozenset({
    # Merrygo beat — a Drum & Bass (adiwav) remix of Khuda Jaane; its Khuda Jaane vocal was
    # overlapping Song 2's lyrics (~45s placed). Use the beat only. (founder decision 2026-07-15)
    # This id is the TRIMMED beat (piano intro 0:00-0:22.68 removed 2026-07-15); the pre-trim id
    # 21daa846… was retired with it.
    "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480",
})


def is_instrumental_only(song_id: str) -> bool:
    """True if this beat should contribute its music only — the planner must not place its own vocal."""
    return song_id in INSTRUMENTAL_ONLY_BEATS
