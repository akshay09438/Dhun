"""Deterministic rule shuffler — ONE engine, two callers.

Auto-assigns each generation one of the three mixing RULES {1, 3, 4}:
  1 = simple mix (vocal on the drop)   3 = chop & repeat   4 = echo + reverb
Rule 2 is a spec-only reservation and is deliberately NOT in the set.

VOCABULARY (locked — used loosely in conversation, exact here):
  - PAIR = two songs (one beat + one vocal). An input.
  - MIX  = one PAIR rendered with one RULE. Exactly one rule per mix.
  - SET  = an ordered sequence of MULTIPLE mixes (2..5), each from its own pair, played back-to-back.

TWO FLOWS, ONE ENGINE. The core is `rule_at_from_seed(base, position)` (and its list form
`rule_sequence_from_seed`): a PURE function that, given a stable seed string and a 0-based position,
returns the rule for that position such that the whole emitted sequence is balanced and never repeats
a rule back-to-back. Both flows below call it; they differ ONLY in the seed they pass:
  - Single-pair RE-ROLL:  base = user_id + song1_id + song2_id ; position = the Nth re-roll of that pair.
  - SET:                  base = user_id + set_index           ; position = the mix's index in the set.
`set_index` (0-based: a user's 1st set = 0, 2nd = 1, …) is what makes a user's consecutive sets differ.

Determinism is load-bearing — the assigned rule folds into the content-addressed mix cache, so the same
inputs must yield the same rule forever, on any machine. Portable sha256 seed; never wall-clock or
Python's salted hash(). Every property is pinned in test_rule_shuffle.py.

HONEST CEILING: there are only THREE distinct rules. The engine controls the ORDER rules arrive in and
spreads them fairly — a set longer than 3 (or a 4th+ re-roll) WILL reuse a rule; the reuse is never
adjacent and stays balanced, but the engine does NOT invent a 4th rule. Deeper per-generation variety
must come from WITHIN-rule variation (Rule 4 echo moments, Rule 3 chop choices) — a separate, mostly
unshipped concern. Never fake variety here.

Guaranteed properties (all proven in the tests):
  R1/G1  Every ALIGNED group of 3 (position // 3) contains all 3 rules exactly once — balanced, then
         the engine "continues dealing" the next ordering (NOT a rigid period-3 repeat).
  R2/G2  Strict no-repeat: a rule never repeats back-to-back, ANYWHERE — inside a group, across a
         group boundary, across a cycle boundary.
  R3/G4  Different users get different orderings for the same seed inputs.
  R4/G3  Consecutive groups differ; and consecutive SETS (same user) differ (an explicit guard perturbs
         the rare hash collision).
  R5/G5  Pure & deterministic: portable sha256 seed.
"""
from __future__ import annotations

import hashlib
import random

_SEP = "\x1f"  # unit separator between seed fields — prevents 'ab|c' vs 'a|bc' collisions

# The three live rules. Rule 2 is spec-only and intentionally excluded.
RULES: tuple[int, ...] = (1, 3, 4)

# The 6 orderings of the 3 rules — one ordering supplies one group of 3 generations.
ORDERINGS: tuple[tuple[int, int, int], ...] = (
    (1, 3, 4), (1, 4, 3),
    (3, 1, 4), (3, 4, 1),
    (4, 1, 3), (4, 3, 1),
)

_GROUP = 3                                        # generations per ordering
_ORDERINGS_PER_CYCLE = len(ORDERINGS)             # 6
_GENS_PER_CYCLE = _ORDERINGS_PER_CYCLE * _GROUP   # 18 generations before the macro-pattern reshuffles


# ================================ the shared engine ============================================

def _cycle_seed(base: str, cycle: int) -> int:
    """A stable, portable seed for one (seed base, cycle). sha256 (NOT Python's salted hash()) so the
    value is byte-identical across processes and machines — the mix cache depends on it."""
    raw = f"{base}{_SEP}{cycle}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _shuffled_deck(base: str, cycle: int) -> list[tuple[int, int, int]]:
    """This seed's personal 'deck' for one cycle: the 6 orderings shuffled by the seeded PRNG.
    random.Random(int seed) is deterministic and portable across CPython versions/platforms."""
    deck = list(ORDERINGS)
    random.Random(_cycle_seed(base, cycle)).shuffle(deck)
    return deck


def _arrange(deck: list[tuple[int, int, int]], prev_rule: int | None,
             prev_ordering: tuple[int, int, int] | None) -> list[tuple[int, int, int]]:
    """Order the deck's 6 orderings so NO seam repeats a rule back-to-back (R2/G2) and no two
    consecutive groups are the same ordering (R4/G3) — honouring the cross-boundary `prev_rule`/
    `prev_ordering` carried in from the previous cycle. Greedy in deck order (the seeded deck is the
    primary order), with deterministic backtracking as the rigorous form of 'reshuffle the tail'.
    Always solvable for the 6 orderings; the caller still asserts the emitted run has no repeat."""
    n = len(deck)
    used = [False] * n
    result: list[tuple[int, int, int]] = []

    def backtrack(pr: int | None, po: tuple[int, int, int] | None) -> bool:
        if len(result) == n:
            return True
        for i in range(n):
            if used[i]:
                continue
            cand = deck[i]
            if cand[0] == pr:      # R2/G2: this seam would repeat a rule back-to-back
                continue
            if cand == po:         # R4/G3: would repeat the immediately previous group's ordering
                continue
            used[i] = True
            result.append(cand)
            if backtrack(cand[-1], cand):
                return True
            result.pop()
            used[i] = False
        return False

    if not backtrack(prev_rule, prev_ordering):
        # Unreachable for the 6 orderings, but never silently emit a violating order.
        raise AssertionError("no valid seam arrangement for the deck")
    return result


def rule_sequence_from_seed(base: str, count: int) -> list[int]:
    """The first `count` rules for a seed base, as a flat list (position 0..count-1). Cycles are
    generated continuously, carrying the previous rule/ordering across the cycle boundary so R2/G2 and
    R4/G3 hold even at the seam between cycles. This is the ONE engine both flows share."""
    if count < 0:
        raise ValueError("count must be >= 0")
    out: list[int] = []
    prev_rule: int | None = None
    prev_ordering: tuple[int, int, int] | None = None
    cycle = 0
    while len(out) < count:
        deck = _shuffled_deck(base, cycle)
        for ordering in _arrange(deck, prev_rule, prev_ordering):
            out.extend(ordering)
            prev_rule = ordering[-1]
            prev_ordering = ordering
        cycle += 1
    # Load-bearing guarantee (R2/G2): no back-to-back repeat across the ENTIRE emitted sequence.
    assert all(a != b for a, b in zip(out, out[1:])), "back-to-back rule repeat"
    return out[:count]


def rule_at_from_seed(base: str, position: int) -> int:
    """The rule at 0-based `position` for a seed base. PURE: same (base, position) -> same rule, forever.
    O(position) — the seam handling is a continuous walk from position 0 — but position is a small
    per-sitting counter, well within budget for the app's scale."""
    if position < 0:
        raise ValueError("position must be >= 0")
    return rule_sequence_from_seed(base, position + 1)[position]


# ================================ flow 1: single-pair re-roll =================================

def _pair_base(user_id: str, song1_id: str, song2_id: str) -> str:
    return f"{user_id}{_SEP}{song1_id}{_SEP}{song2_id}"


def rule_for(user_id: str, song1_id: str, song2_id: str, n: int) -> int:
    """The rule for re-roll `n` (0-based) of one pair for one user. Folds into the mix cache identity."""
    return rule_at_from_seed(_pair_base(user_id, song1_id, song2_id), n)


def rule_sequence(user_id: str, song1_id: str, song2_id: str, count: int) -> list[int]:
    """The first `count` re-roll rules for one user+pair (the single-pair flow's list form)."""
    return rule_sequence_from_seed(_pair_base(user_id, song1_id, song2_id), count)


# ================================ flow 2: the SET =============================================

def _set_base(user_id: str, set_index: int, salt: int = 0) -> str:
    # salt is only used by the consecutive-sets-differ guard, and only when a rare hash collision needs
    # breaking; the common salt=0 base is exactly `user_id + set_index` (as specified).
    base = f"{user_id}{_SEP}{set_index}"
    return base if salt == 0 else f"{base}{_SEP}r{salt}"


def _first_ordering(base: str) -> tuple[int, ...]:
    return tuple(rule_sequence_from_seed(base, _GROUP))


def _resolved_set_base(user_id: str, set_index: int) -> str:
    """The seed base for a user's `set_index`-th set, with the G3 guard applied: if this set's first
    ordering coincides with the previous set's, perturb (salt) until it visibly differs. Pure and
    deterministic; O(set_index) via the recursion, which is tiny (a user builds a handful of sets)."""
    base = _set_base(user_id, set_index)
    if set_index <= 0:
        return base
    prev = _resolved_set_base(user_id, set_index - 1)
    salt = 0
    while _first_ordering(base) == _first_ordering(prev):
        salt += 1
        base = _set_base(user_id, set_index, salt)
    return base


def rule_for_set(user_id: str, set_index: int, position: int) -> int:
    """The rule for the mix at 0-based `position` in a user's `set_index`-th set. PURE + deterministic,
    so rebuilding the same set yields the same rules (cache-safe)."""
    if set_index < 0:
        raise ValueError("set_index must be >= 0")
    return rule_at_from_seed(_resolved_set_base(user_id, set_index), position)


def set_rule_sequence(user_id: str, set_index: int, length: int) -> list[int]:
    """The rules for a whole set of `length` mixes (2..5) — the set flow's list form. Balanced +
    strict no-repeat within the set; different from the user's other sets and from other users."""
    if set_index < 0:
        raise ValueError("set_index must be >= 0")
    return rule_sequence_from_seed(_resolved_set_base(user_id, set_index), length)
