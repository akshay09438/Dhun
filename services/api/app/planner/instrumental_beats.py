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

from app.models import TrackAnalysis

INSTRUMENTAL_ONLY_BEATS: frozenset[str] = frozenset({
    # Merrygo beat — a Drum & Bass (adiwav) remix of Khuda Jaane; its Khuda Jaane vocal was
    # overlapping Song 2's lyrics (~45s placed). Use the beat only. (founder decision 2026-07-15)
    # This id is the TRIMMED beat (piano intro 0:00-0:22.68 removed 2026-07-15); the pre-trim id
    # 21daa846… was retired with it.
    "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480",
    # Rapture (Black Coffee) — has NO real lyrics (founder's ear, 2026-08-07). Its vocal STEM is
    # instrumental bleed/pads that the separator mis-heard as singing, so its analysis reads a single
    # vocal region spanning the whole song. Weaving that false "vocal" in overlapped Song 2 and got the
    # mix skipped (R1). Mark it music-only — the right call for a beat with no vocal. (founder decision)
    "7f0b66c94d2be61f18a64485dba0a33b5f4387ccce2ff1b5d23aa7da469076eb",
})


def vocal_coverage(a1: TrackAnalysis) -> float:
    """The fraction of the track Song 1's own vocal covers (0.0–1.0), from its analysis. A near-1.0 value
    is a red flag — a real beat rarely sings the whole song, so it usually means the vocal separator
    mis-heard instrumental content as singing. Feeds the backend anomaly report ONLY — it never decides
    silencing (a human ear does, via the hand-list above)."""
    regions = [(s, e) for s, e in (a1.vocal_regions or []) if e > s]
    if not regions:
        return 0.0
    track_end = (a1.beats[-1] if a1.beats else 0.0) or max(e for _, e in regions)
    if track_end <= 0:
        return 0.0
    covered = sum(min(e, track_end) - s for s, e in regions)
    return min(1.0, covered / track_end)


def is_instrumental_only(a1: TrackAnalysis) -> bool:
    """True ONLY if this beat is on the hand-picked music-only list. A beat is NEVER auto-silenced from a
    coverage number — that wrongly muted beats with real vocals (e.g. 'I Adore You', which reads ~99%
    vocal but sings fine). Which beats are instrumental is a founder/ear decision, not the app's guess."""
    return a1.song_id in INSTRUMENTAL_ONLY_BEATS
