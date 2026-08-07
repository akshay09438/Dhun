"""Deterministic rule shuffler — the determinism contract the mix cache depends on.

CHANGE 1 (2026-08-07): the manual per-song rule buttons go away; each generation is auto-assigned one
of the 3 rules {1,3,4} by `rule_shuffle.rule_for`. These tests pin R1-R5 (see the module docstring)
HARD, because the assigned rule folds into the content-addressed mix id — a drift here would silently
re-key or corrupt the cache.
"""
from collections import Counter

import pytest

from app.planner import rule_shuffle as rs

# One fixed pair (content-addressed song ids are 64-hex in the app; any stable strings work here).
S1 = "a" * 64
S2 = "b" * 64
RULESET = set(rs.RULES)  # {1, 3, 4}


def _seq(user: str, count: int, s1: str = S1, s2: str = S2) -> list[int]:
    return rs.rule_sequence(user, s1, s2, count)


def _groups(seq: list[int]) -> list[tuple[int, ...]]:
    """The ALIGNED groups of 3 (index // 3) — the runs the balance guarantee (R1) is about."""
    return [tuple(seq[i : i + 3]) for i in range(0, len(seq) - len(seq) % 3, 3)]


# ---- R5: pure & deterministic ------------------------------------------------------------------

def test_rule_for_is_pure_same_inputs_same_output():
    for n in range(0, 40):
        assert rs.rule_for("u1", S1, S2, n) == rs.rule_for("u1", S1, S2, n)


def test_rule_for_matches_the_sequence():
    seq = _seq("u1", 30)
    for n in range(30):
        assert rs.rule_for("u1", S1, S2, n) == seq[n]


def test_seed_uses_sha256_not_pythons_salted_hash():
    # A golden vector: sha256-seeded, so identical on every machine/run regardless of PYTHONHASHSEED.
    # If this changes, the mix cache identity for auto-assigned rules has drifted — investigate before
    # updating the expected values.
    assert _seq("golden-user", 9) == [3, 4, 1, 4, 3, 1, 4, 1, 3]


def test_negative_index_rejected():
    with pytest.raises(ValueError):
        rs.rule_for("u1", S1, S2, -1)


# ---- R2: strict no back-to-back repeat, anywhere ------------------------------------------------

def test_no_back_to_back_repeat_across_many_seeds_and_a_long_run():
    # 100 generations spans ~6 cycles (18 each), so this exercises within-group, group-boundary AND
    # cycle-boundary seams for every seed.
    for i in range(200):
        seq = _seq(f"user-{i}", 100)
        assert all(a != b for a, b in zip(seq, seq[1:])), f"back-to-back repeat for user-{i}: {seq}"


def test_no_back_to_back_across_the_cycle_boundary_specifically():
    # Indices 17->18 is the first cycle seam; check a window around it for several users.
    for i in range(50):
        seq = _seq(f"cyc-{i}", 24)
        assert seq[17] != seq[18]


# ---- R1: every aligned group of 3 contains all 3 rules exactly once -----------------------------

def test_every_aligned_group_is_a_permutation_of_all_three_rules():
    for i in range(200):
        for g in _groups(_seq(f"bal-{i}", 60)):
            assert Counter(g) == Counter(rs.RULES), f"unbalanced group {g} for bal-{i}"


def test_rules_emitted_are_only_the_three_live_rules():
    for i in range(50):
        assert set(_seq(f"valid-{i}", 60)) <= RULESET


# ---- R4: consecutive groups are different orderings --------------------------------------------

def test_consecutive_groups_differ_including_cycle_boundary():
    for i in range(200):
        groups = _groups(_seq(f"grp-{i}", 60))  # 20 groups -> spans multiple cycles
        for a, b in zip(groups, groups[1:]):
            assert a != b, f"repeated ordering {a} for grp-{i}"


# ---- R3: different users get different orderings for the same pair ------------------------------

def test_two_different_users_diverge_on_the_same_pair():
    assert _seq("alice", 9) != _seq("bob", 9)


def test_users_do_not_all_get_the_same_first_rule():
    # The spec's headline: 100 users on one pair must not all get the same rule first.
    firsts = {rs.rule_for(f"user-{i}", S1, S2, 0) for i in range(100)}
    assert len(firsts) >= 2
    # And the full 9-gen sequences are not all identical either.
    seqs = {tuple(_seq(f"user-{i}", 9)) for i in range(100)}
    assert len(seqs) > 1


def test_same_user_different_pair_can_differ():
    # The pair is part of the seed, so a different pair is a different deck (sanity, not a hard law).
    a = _seq("same-user", 9, s1="c" * 64, s2="d" * 64)
    b = _seq("same-user", 9, s1="e" * 64, s2="f" * 64)
    assert a != b


# ---- CHANGE 2: 4- and 5-generation sittings still satisfy R1/R2/R4 -----------------------------

def test_sessions_of_four_and_five_satisfy_r1_r2_r4():
    # The per-session cap rose 2 -> 5. A sitting is just a prefix of the emitted sequence, and every
    # seam is handled identically, so R1/R2/R4 must hold for length-4 and length-5 sittings too.
    for n in (4, 5):
        for i in range(100):
            seq = _seq(f"sit-{i}", n)
            assert all(a != b for a, b in zip(seq, seq[1:])), f"R2 broke in a {n}-gen sitting: {seq}"
            groups = _groups(seq)  # complete aligned groups only
            for g in groups:
                assert Counter(g) == Counter(rs.RULES), f"R1 broke in a {n}-gen sitting: {g}"
            for a, b in zip(groups, groups[1:]):  # R4 (vacuous at n<=5: at most one full group)
                assert a != b


# ---- SET flow: seed = user + set_index; positions = the mix's index in the set -----------------
# A SET is 2..5 mixes (each its own pair) played back-to-back. Same shuffler engine, different seed.

def _set(user: str, set_index: int, length: int) -> list[int]:
    return rs.set_rule_sequence(user, set_index, length)


def test_set_no_adjacent_repeat_lengths_2_to_5():  # G2
    for n in (2, 3, 4, 5):
        for i in range(100):
            seq = _set(f"u-{i}", 0, n)
            assert all(a != b for a, b in zip(seq, seq[1:])), f"G2 broke: len {n}, {seq}"


def test_set_first_three_are_balanced():  # G1 ("first 3 balanced, then continues dealing")
    for i in range(100):
        seq = _set(f"u-{i}", 0, 5)
        assert Counter(seq[:3]) == Counter(rs.RULES), seq


def test_consecutive_sets_differ_for_the_same_user():  # G3 (with the explicit perturb guard)
    for i in range(100):
        u = f"user-{i}"
        a, b, c = _set(u, 0, 5), _set(u, 1, 5), _set(u, 2, 5)
        assert a != b and b != c
        assert a[:3] != b[:3] and b[:3] != c[:3]  # the guard differs the FIRST ordering specifically


def test_two_users_get_different_sets():  # G4
    seqs = {tuple(_set(f"user-{i}", 0, 5)) for i in range(100)}
    assert len(seqs) > 1
    assert len({_set(f"user-{i}", 0, 5)[0] for i in range(100)}) >= 2  # not all the same first rule


def test_set_is_deterministic():  # G5
    for idx in range(30):
        assert _set("stable", idx, 5) == _set("stable", idx, 5)
    assert rs.rule_for_set("stable", 3, 2) == rs.rule_for_set("stable", 3, 2)


def test_single_and_set_flows_share_one_engine():  # both flows are thin wrappers over rule_at_from_seed
    base = "any-seed-string"
    seq = rs.rule_sequence_from_seed(base, 12)
    for pos in range(12):
        assert rs.rule_at_from_seed(base, pos) == seq[pos]  # identical (base, position) -> identical rule
    # the single-pair flow is exactly the shared core over its pair base:
    assert rs.rule_for("U", "S1", "S2", 4) == rs.rule_at_from_seed("U\x1fS1\x1fS2", 4)


def test_set_negative_indices_rejected():
    with pytest.raises(ValueError):
        rs.rule_for_set("u", -1, 0)
    with pytest.raises(ValueError):
        rs.rule_for_set("u", 0, -1)


# ---- macro structure: reshuffle after a full cycle ---------------------------------------------

def test_macro_pattern_can_change_after_18_generations():
    # Cycle 0 (gens 0..17) and cycle 1 (gens 18..35) are seeded differently, so the ordering of
    # orderings should not be forced to repeat. (They MAY share some orderings; they must not be the
    # identical 18-length block.)
    seq = _seq("macro", 36)
    assert seq[0:18] != seq[18:36]
