"""Key-matching DECISION layer (app/planner/keys.py) — the PURE, no-audio brain that decides the
minimal semitone shift and refuses to shift when a key isn't trustworthy.

Two things are proven here:
  1. fuzzy_key_shift — the founder-approved fuzzy keymixing rule (match the Camelot NUMBER, ignore the
     letter; compatible = same number or ±1; minimum shift; capped; None past the cap). Ported from the
     throwaway `scratchpad/fuzzy_key.py` unit table (24 hand-computed cases) PLUS an arithmetic
     cross-check of the Camelot math against an independent pitch-class computation.
  2. resolve_key_shift — the CONFIDENCE GATE. The whole point of the gate is that a wrong-direction
     shift is worse than none, so a flagged song, a missing key, or a shaky (low-confidence) key must
     force shift 0. Each of those refusal paths gets a test; a clean, confident pair that needs a shift
     gets the real nonzero answer.
"""

from types import SimpleNamespace

from app.planner import keys


# --------------------------------------------------------------------------- #
# fuzzy_key_shift — the 24-case table (ported verbatim from the throwaway) + arithmetic cross-check.
# --------------------------------------------------------------------------- #

# (vocal_camelot, beat_camelot, cap, expected_shift). Hand-computed; covers same-number/letter-ignored,
# ±1, wrap-around 12<->1, needing a 2-st shift, a -1 shift, cap=1 unreachable (None), and cap=0.
_FUZZY_CASES = [
    ("8A", "8A", 2, 0), ("8A", "8B", 2, 0), ("8B", "8A", 2, 0),      # same number, letter ignored
    ("8A", "9A", 2, 0), ("8A", "7A", 2, 0), ("8A", "9B", 2, 0),      # ±1 number
    ("12A", "1A", 2, 0), ("1A", "12B", 2, 0),                        # wrap-around 12<->1
    ("11A", "12A", 2, 0), ("12B", "1B", 2, 0), ("2A", "2B", 2, 0),
    ("6A", "6B", 2, 0), ("10A", "10A", 2, 0),
    ("8A", "10A", 2, +2), ("8A", "6A", 2, -2), ("8A", "11A", 2, +2),  # need a 2-st shift
    ("8A", "5A", 2, -2), ("9A", "7A", 2, -2), ("1A", "3A", 2, +2),
    ("3A", "8A", 2, -1), ("3B", "8A", 2, -1),                        # A#minor vocal -1st -> A minor
    ("8A", "10A", 1, None), ("8A", "6A", 1, None),                   # cap=1 -> unreachable
    ("8A", "8A", 0, 0),
]


def test_fuzzy_key_shift_unit_table():
    """The 24 hand-computed cases must all match — the founder-approved fuzzy rule, exactly. A wrong
    sign, a wrong minimum, a broken wrap, or a missing cap flips at least one of these red."""
    failures = []
    for vk, bk, cap, exp in _FUZZY_CASES:
        got = keys.fuzzy_key_shift(vk, bk, cap=cap)
        if got != exp:
            failures.append(f"{vk}->{bk} cap{cap}: got {got}, expected {exp}")
    assert not failures, "fuzzy_key_shift mismatches:\n  " + "\n  ".join(failures)


def test_fuzzy_key_shift_returns_none_on_unparseable():
    """A garbage code can't be parsed into a Camelot number — the function must return None (skip the
    shift), never raise into the render path."""
    assert keys.fuzzy_key_shift("not-a-key", "8A") is None
    assert keys.fuzzy_key_shift("8A", "") is None


def test_camelot_shift_arithmetic_cross_check():
    """CROSS-CHECK the Camelot math (+1 semitone = +7 Camelot numbers mod 12) against an INDEPENDENT
    pitch-class computation for every number and every shift in ±6 — so the table above rests on
    verified arithmetic, not a memorized identity. (Mirrors the throwaway's self-test.)"""
    def pc_of(n, letter):
        base = 9 if letter == "A" else 0
        return (base + 7 * (n - 8)) % 12

    def num_of_pc(pc, letter):
        base = 9 if letter == "A" else 0
        n0 = (7 * ((pc - base) % 12)) % 12
        return ((n0 + 8 - 1) % 12) + 1

    for n in range(1, 13):
        for letter in "AB":
            for s in range(-6, 7):
                independent = num_of_pc((pc_of(n, letter) + s) % 12, letter)
                assert keys._num_after_shift(n, s) == independent, (
                    f"num_after_shift({n},{s}) disagrees with the pitch-class computation")


# --------------------------------------------------------------------------- #
# resolve_key_shift — the confidence gate.
# --------------------------------------------------------------------------- #

def _song(song_id="c" * 64, camelot="8A", confidence=0.9):
    """A duck-typed analysis shim carrying only what resolve_key_shift reads: song_id + key.camelot +
    key.confidence."""
    return SimpleNamespace(song_id=song_id, key=SimpleNamespace(camelot=camelot, confidence=confidence))


def test_resolve_skips_shift_for_a_flagged_song_id():
    """GATE (flagged key): a song whose key a 2nd detector disagreed with is in KEY_UNTRUSTED_SONG_IDS;
    ANY pair touching it must resolve to shift 0, with a reason that says the key is flagged — a
    wrong-direction shift is worse than none. Uses a real flagged id from the module's own frozenset."""
    flagged_id = next(iter(keys.KEY_UNTRUSTED_SONG_IDS))
    # The vocal (a2) is the flagged song; the beat (a1) is clean — a shift WOULD be picked but for the gate.
    beat = _song(song_id="a" * 64, camelot="10A", confidence=0.95)
    vocal = _song(song_id=flagged_id, camelot="8A", confidence=0.95)
    shift, reason = keys.resolve_key_shift(beat, vocal)
    assert shift == 0, reason
    assert "flag" in reason.lower()


def test_resolve_skips_shift_on_low_confidence():
    """GATE (shaky key): if either detected key's confidence is below KEY_CONF_MIN (0.50) the shift
    DIRECTION can't be trusted, so shift 0. The pair below would otherwise want +2 (8A vocal into a 10A
    beat), so this fails for the gate, not for the arithmetic."""
    beat = _song(song_id="a" * 64, camelot="10A", confidence=0.95)
    vocal = _song(song_id="b" * 64, camelot="8A", confidence=0.40)  # < 0.50
    shift, reason = keys.resolve_key_shift(beat, vocal)
    assert shift == 0, reason
    assert "confidence" in reason.lower()


def test_resolve_skips_shift_on_a_missing_key():
    """GATE (no key): a song with no detected key at all -> shift 0, reason names the missing key. Can't
    guess a shift direction from nothing."""
    beat = _song(song_id="a" * 64, camelot="10A", confidence=0.95)
    vocal = SimpleNamespace(song_id="b" * 64, key=None)  # never analyzed a key
    shift, reason = keys.resolve_key_shift(beat, vocal)
    assert shift == 0, reason
    assert "key" in reason.lower()


def test_resolve_returns_the_real_nonzero_shift_for_a_clean_confident_clash():
    """The PAYOFF: a clean, high-confidence pair that genuinely clashes must get the correct nonzero
    shift (not swallowed by the gate). 8A vocal into a 10A beat needs +2 semitones (a1=beat, a2=vocal)."""
    beat = _song(song_id="a" * 64, camelot="10A", confidence=0.95)
    vocal = _song(song_id="b" * 64, camelot="8A", confidence=0.90)
    shift, reason = keys.resolve_key_shift(beat, vocal)
    assert shift == 2, reason
    assert "8A" in reason and "10A" in reason


def test_resolve_zero_shift_when_already_compatible():
    """A clean pair that is ALREADY key-compatible resolves to 0 with a 'no shift' reason — proving 0
    from compatibility reads differently from 0 from the gate (both are logged, never silent)."""
    beat = _song(song_id="a" * 64, camelot="8A", confidence=0.95)
    vocal = _song(song_id="b" * 64, camelot="8B", confidence=0.90)  # same number -> compatible
    shift, reason = keys.resolve_key_shift(beat, vocal)
    assert shift == 0, reason
    assert "already compatible" in reason.lower()
