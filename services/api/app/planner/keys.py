"""Key-matching DECISION layer (pure, no audio): given a pair, decide the minimal semitone shift
to move Song 2's vocal into a compatible key with Song 1's beat, with a CONFIDENCE GATE that
refuses to shift when a song's detected key isn't trusted (a wrong-direction shift is worse than
none). The EXECUTOR that actually pitch-shifts audio is `app/audio/pitch.py`; the referee that
independently re-checks the result is `app/planner/validate.py`.

Fuzzy keymixing (founder-approved): match the Camelot NUMBER, IGNORE the letter; compatible = same
number or ±1 number (circular); shift the MINIMUM semitones to reach any compatible key, capped at
±2 st. Camelot math (verified): +1 semitone = +7 Camelot numbers mod 12.
"""
from __future__ import annotations

CAP_SEMITONES = 2  # named taste constant — the industry / CDJ-3000 ceiling (founder-approved)
KEY_CONF_MIN = 0.50  # below this a detected key is too shaky to trust the shift DIRECTION at all

# Songs whose key a SECOND independent detector (Temperley) disagreed with on the Camelot NUMBER
# (harmful — a wrong number flips the shift direction). Skip auto-shift on any pair touching these
# until the founder ear-confirms their key. REMOVE a song_id here once its key is ear-checked.
# (Names for humans: Anchor Point, Dooriyan, Rapture, Wari Jawa, With You.)
KEY_UNTRUSTED_SONG_IDS = frozenset({
    "2c17fc64b6928f0499a306402b676bc62e3118588e42494c8ec7063a7a948267",  # Anchor Point
    "c4b28366d0bd8a5dd0447d1dece9e204ae45f648ee066e0fc9bc04a068ba8b34",  # Dooriyan
    "7f0b66c94d2be61f18a64485dba0a33b5f4387ccce2ff1b5d23aa7da469076eb",  # Rapture
    "0bcbcd12d965a7d03f314424670768ed9074c18f6f2af961fb05d77c803f3d7b",  # Wari Jawa
    "ae132f3a444f5121d75097a44110a0323365e6dc4a8d0736a924c00b2ac210c1",  # With You
})


def _parse_camelot(code: str) -> tuple[int, str]:
    code = code.strip().upper()
    return int(code[:-1]), code[-1]  # (number 1..12, letter 'A'/'B')


def _num_after_shift(num: int, s: int) -> int:
    """Camelot number after shifting pitch by s semitones (letter/mode unchanged)."""
    return ((num - 1 + 7 * s) % 12) + 1


def _numbers_compatible(na: int, nb: int) -> bool:
    """Fuzzy rule: same number or ±1 number, letter ignored."""
    d = abs(na - nb) % 12
    return min(d, 12 - d) <= 1


def fuzzy_key_shift(vocal_camelot: str, beat_camelot: str, cap: int = CAP_SEMITONES) -> int | None:
    """Minimal semitone shift (nearest 0) making the vocal's Camelot number compatible with the
    beat's, capped at ±cap. 0 if already compatible; None if unreachable within cap or unparseable."""
    try:
        nv, _ = _parse_camelot(vocal_camelot)
        nb, _ = _parse_camelot(beat_camelot)
    except (ValueError, IndexError, AttributeError):
        return None
    for s in sorted(range(-cap, cap + 1), key=lambda x: (abs(x), x)):  # 0,-1,+1,-2,+2
        if _numbers_compatible(_num_after_shift(nv, s), nb):
            return s
    return None


def resolve_key_shift(a1, a2) -> tuple[int, str]:
    """Decide the vocal shift for a pair, with the confidence gate. `a1` = beat (Song 1), `a2` = vocal
    (Song 2). Returns (semitones, reason). semitones == 0 means "do not shift" (mix as-is); the reason
    is always logged so a skipped shift is never silent."""
    if getattr(a1, "song_id", None) in KEY_UNTRUSTED_SONG_IDS or getattr(a2, "song_id", None) in KEY_UNTRUSTED_SONG_IDS:
        return 0, "key-skip: a song's key is flagged (2nd detector disagreed) and not ear-confirmed"
    k1 = getattr(a1, "key", None)
    k2 = getattr(a2, "key", None)
    if not (k1 and k2 and getattr(k1, "camelot", None) and getattr(k2, "camelot", None)):
        return 0, "key-skip: a song has no detected key"
    if min(float(k1.confidence), float(k2.confidence)) < KEY_CONF_MIN:
        return 0, f"key-skip: key confidence too low to trust the shift direction (< {KEY_CONF_MIN})"
    s = fuzzy_key_shift(k2.camelot, k1.camelot)
    if s is None:
        return 0, "key-skip: no compatible key within the ±2 st cap"
    if s == 0:
        return 0, f"key-ok: {k2.camelot} already compatible with {k1.camelot} (no shift)"
    return s, f"key-match: shift vocal {k2.camelot} -> compatible with {k1.camelot} by {s:+d} st"
