"""Per-beat VOCAL ENTRY FLOOR — the earliest moment Song 2's vocal may enter.

By default the arrangement spreads Song 2's vocal across the WHOLE beat song (an energy arc across
the thirds — Handbook H1/H2). That is right for a house track built to carry a guest vocal end to
end, but wrong for a long track with its own strong first act: the guest vocal keeps interrupting a
song that hasn't finished saying its own piece.

For those beats we mark, BY EAR, the earliest point Song 2 may sing — keyed by the beat's content id,
exactly like the hooks (app/planner/hooks.py) and the main drops (app/planner/main_drops.py). Before
that point the beat plays AS ITSELF (its own vocal included); from that point on Song 2's vocal
arranges as normal, and the beat's own vocal hands off underneath it via the existing natural
hand-off (m5f.1) — no imposed fade.

The natural mark is where the BEAT starts singing: Song 2's vocal rides in with the beat's own
lyrics, so the two never talk over an instrumental stretch that was working fine on its own.

Times are in SECONDS on the song's own (native) timeline; the planner snaps each to the nearest
downbeat and re-times it onto the (possibly tempo-shifted) planning grid, exactly like a main drop.
A beat NOT listed keeps today's whole-song arrangement — this changes nothing for any other song.
"""

from __future__ import annotations

VOCAL_ENTRY_EARLIEST: dict[str, float] = {
    # Innerbloom (RÜFÜS DU SOL) — a 9:38 track with a long first act of its own. Founder call
    # (2026-07-16): nothing of Song 2 until Innerbloom's own verse starts. Its buildup runs from
    # ~5:45 (the 5:46-6:02 break, then 6:02-6:17 instrumental) and its lyrics start at 6:17 — so
    # Song 2 enters THERE, riding in with Innerbloom's own singing, which then decays away under it.
    "2471e18e1eb820114c0782501babac43b6e5b52c06254da4c1fe0d9e8369c406": 377.0,  # 6:17
}


def vocal_entry_earliest_for(song_id: str) -> float:
    """Earliest time (seconds, native timeline) Song 2's vocal may enter over this beat.

    0.0 means no restriction — the arrangement spans the whole song, as it does for every beat that
    is not hand-marked here.

    A vocal-RICH beat with a guest-verse window (app/planner/beat_guest_verse.py) holds Song 2 out
    until that window ENDS, so the beat sings its own line first and the two never overlap.
    """
    from app.planner import beat_guest_verse  # local import avoids an import cycle
    gv = beat_guest_verse.guest_verse_for(song_id)
    if gv is not None:
        return gv[1]  # Song 2 enters right after the beat's guest verse
    return VOCAL_ENTRY_EARLIEST.get(song_id, 0.0)
