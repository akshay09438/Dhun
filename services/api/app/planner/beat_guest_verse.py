"""Per-beat GUEST-VERSE window — how a vocal-RICH beat sings its own lyrics, then hands off.

Some catalog beats are also full vocal songs (Faded, Lean On, Wake Me Up). If we weave their vocal
in everywhere it fights Song 2 (R1), and if we mute it entirely we throw away a great hook. The
founder's rule (2026-08-08, ear-approved on Faded x Dooriyan / Lean On x Khuda Jaane / Wake Me Up x
Don't Start Now): the beat sings ONE hand-picked window — its best lyric line — and then trades the
mic to Song 2, which carries the rest (its own hook included). One voice at a time.

Each value is (start, end) in SECONDS on the beat's own (native) timeline — the stretch where the
beat sings its guest verse. When a beat is listed here the planner:
  * places ONLY that window as the beat's own vocal (never the whole song), and
  * holds Song 2 out until the window ends (via vocal_windows, which reads this list), so the two
    never overlap, then Song 2 arranges as normal from there.
It is TRUSTED even on a shaky grid (e.g. Lean On) because the window is founder-verified by ear — so
this bypasses the usual confidence gate.

Picked BY EAR (the vocal detector can't be trusted on these — Lean On reads as one non-stop blob, and
its 0:49 "hook" is humming, not lyrics, which is why its window is the 0:29-0:45 lyric line instead).
The 200-song catalog goal is to auto-detect this window; until the sensors are strong enough, it is a
hand-list, exactly like hooks.py / main_drops.py.

NOTE (open refinement, 2026-08-08): the window END can cut a sung line abruptly. For a beat with a
real phrase gap the end should snap there; for a non-stop singer (Lean On) the render must fade the
beat's vocal down at the hand-off. That fade is a render-engine change, tracked separately.
"""
from __future__ import annotations

from app.planner import rule_shuffle

GUEST_VERSE: dict[str, tuple[float, float]] = {
    # Lean On (Major Lazer & DJ Snake) — the 0:29-0:45 LYRIC line (not the 0:49 hummed hook). Grid is
    # shaky (regularity 0.33) but the window is ear-verified, so it's trusted anyway.
    "ed2c86b75c81961842d7ea6509d0d962efd1798c49e45bed01395db0d49bcc46": (29.0, 45.0),
    # Wake Me Up (Avicii) — its chorus hook.
    "e6722353c4251a3f9af0a76ab620b22f61fa6e385846ae67073debafa6acf1ad": (38.78, 69.81),
    # Faded (Alan Walker) — its chorus hook.
    "f61ea8edc6c56a0a1da0de64d26768618e6007262fbca7738d8571ccfa92c7fa": (31.66, 54.17),
    # Closer (The Chainsmokers ft. Halsey) — its hook line (founder-marked 0:51-1:10, 2026-08-08).
    "3f260b5cadb5a20ca475f50553f4d8512ed2764ba9f4d7988f9c1e0111d25f4e": (51.0, 70.0),
    # Confusion (Drake, Honestly Nevermind Remix) — wired 2026-08-13. It is emphatically a vocal-RICH
    # beat: analysis found 21 vocal regions across the track, so without a window Drake would sing
    # over the whole thing and fight Song 2 everywhere (the R1 one-lead-voice guard would then skip
    # the mix rather than ship two voices at once). The window is the founder's own marked hook from
    # scripts/song_marks.csv, 1:44-2:00. NOT yet ear-verified as a hand-off point — the marks were
    # made as "the best bit", which is not the same question as "the cleanest place to pass the mic".
    "a066e170f852d01b626e8f54dfceeab338c6a6e820dc88b493094adf8adb2712": (104.12, 120.62),
}


def guest_verse_for(song_id: str) -> tuple[float, float] | None:
    """The (start, end) window a vocal-rich beat sings before handing the mic to Song 2, or None."""
    return GUEST_VERSE.get(song_id)


# Rule 3 (chop & repeat) has its OWN beat-vocal logic (routes/mix._render_rule3): for a vocal-heavy
# beat it finds too little instrumental gap and DROPS the beat's vocal entirely — which silently throws
# away the guest verse (the "Wake Me Up x Wari Jawa: no Wake Me Up lyrics" bug; Lean On only worked
# because it landed on rule 1/4). Until chop learns to keep the guest verse, a vocal-rich beat must not
# be chopped — swap rule 3 for rule 4 (echo), which renders via render_mix and honours the guest verse.
# Deterministic (pure function of the song id + rule), so the mix cache identity stays stable.
_CHOP_RULE = 3
_GUEST_VERSE_FALLBACK_RULE = 4


def no_chop_rule(song1_id: str, rule: int) -> int:
    """Remap the chop rule to a guest-verse-safe rule for a vocal-rich beat; every other case unchanged."""
    if rule == _CHOP_RULE and guest_verse_for(song1_id) is not None:
        return _GUEST_VERSE_FALLBACK_RULE
    return rule


def available_rules(song1_id: str) -> tuple[int, ...]:
    """The mixing rules ACTUALLY usable for this beat. A guest-verse beat can't be chopped (rule 3 would
    drop its guest vocal), so only {simple(1), echo(4)} remain; every other beat gets the full {1,3,4}.
    The shuffler picks from this set up front, so the effective rule the user hears never repeats
    back-to-back (the old post-hoc chop->echo remap collapsed 3 into 4 and produced two echoes in a row)."""
    if guest_verse_for(song1_id) is not None:
        return (1, _GUEST_VERSE_FALLBACK_RULE)  # (1, 4) — simple + echo, in ascending rule order
    return rule_shuffle.RULES
