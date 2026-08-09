"""The mixing-rule shuffler must never put two rules (1/3/4) back-to-back — the EFFECTIVE rule the
user hears, after a guest-verse beat's chop(3) is excluded. Guards the fix for the sanity-check finding
that guest-verse beats collapsed 3->4 and produced two echoes in a row. Also pins cache-stability: a
NORMAL beat's rule assignment is byte-identical to the old shuffler, so its cached mixes never change."""
from app.planner import rule_shuffle, beat_guest_verse

_GV_ID = next(iter(beat_guest_verse.GUEST_VERSE))  # a real guest-verse beat id (Faded/Wake Me Up/…)
_NORMAL_ID = "0" * 64                               # not in GUEST_VERSE -> full {1,3,4}
_V = "b" * 64
_USERS = ("u1", "u2", "anon-device-xyz")


def _no_repeat(seq):
    return all(a != b for a, b in zip(seq, seq[1:]))


def test_available_rules_reflects_what_a_beat_can_actually_do():
    assert beat_guest_verse.available_rules(_GV_ID) == (1, 4)         # guest-verse: simple + echo only
    assert beat_guest_verse.available_rules(_NORMAL_ID) == rule_shuffle.RULES == (1, 3, 4)


def test_guest_verse_reroll_never_repeats_and_never_chops():
    allowed = beat_guest_verse.available_rules(_GV_ID)
    for user in _USERS:
        eff = [rule_shuffle.rule_for_available(user, _GV_ID, _V, n, allowed) for n in range(12)]
        assert set(eff) <= {1, 4}, eff          # the chop rule (3) never reaches a guest-verse beat
        assert _no_repeat(eff), eff             # never two of the same style back-to-back
        assert set(eff) == {1, 4}               # both styles still appear (real variety, just alternating)


def test_normal_beat_reroll_is_byte_identical_to_the_old_shuffle():
    allowed = beat_guest_verse.available_rules(_NORMAL_ID)  # (1,3,4)
    for user in _USERS:
        for n in range(18):
            assert (rule_shuffle.rule_for_available(user, _NORMAL_ID, _V, n, allowed)
                    == rule_shuffle.rule_for(user, _NORMAL_ID, _V, n))


def test_set_never_repeats_across_mixed_guest_verse_and_normal_beats():
    allowed = [beat_guest_verse.available_rules(x) for x in
               (_GV_ID, _NORMAL_ID, _GV_ID, _NORMAL_ID, _GV_ID)]  # a worst-case 5-mix alternating set
    for u in _USERS:
        for si in range(4):
            rules = rule_shuffle.set_rules_for(u, si, allowed)
            assert len(rules) == 5
            for r, al in zip(rules, allowed):
                assert r in al                  # each position uses only that beat's usable styles
            assert _no_repeat(rules), rules     # no two consecutive mixes share a style


def test_all_guest_verse_set_alternates_simple_and_echo():
    allowed = [(1, 4)] * 5
    for u in _USERS:
        rules = rule_shuffle.set_rules_for(u, 0, allowed)
        assert set(rules) <= {1, 4}
        assert _no_repeat(rules), rules


def test_normal_set_is_byte_identical_to_the_old_set_sequence():
    allowed = [rule_shuffle.RULES] * 5
    for u in _USERS:
        for si in range(3):
            assert rule_shuffle.set_rules_for(u, si, allowed) == rule_shuffle.set_rule_sequence(u, si, 5)


def test_sequence_over_is_deterministic():
    # same inputs -> same sequence, forever (the mix cache depends on it)
    a = rule_shuffle.sequence_over("seed-x", 10, (1, 4))
    b = rule_shuffle.sequence_over("seed-x", 10, (1, 4))
    assert a == b and _no_repeat(a) and set(a) == {1, 4}
