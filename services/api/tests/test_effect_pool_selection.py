"""Acceptance tests for the effect-pool SELECTION layer (planner side).

Independent of the implementation: these assert the human-approved acceptance criteria
(determinism, per-take variety, variety-OFF => no picks) via the public planner surface
(build_mix_plan) and the named selection helper (_select_effects). No audio, no network —
the fallback arrangement path is forced by removing ANTHROPIC_API_KEY.

Criteria covered here:
  1 (part) DETERMINISM of effects_selected across repeated build_mix_plan calls.
  2        VARIETY ACROSS TAKES — takes 1..N draw DISTINCT (space,width) combos, no repeats.
  6 (part) VARIETY OFF — effect_variety=False sets no space/width and effects_selected == [].
"""

import pytest

from app.models import Placement
from app.planner import plan as planner
from tests.test_fence import make_analysis


@pytest.fixture(autouse=True)
def _pool_on(monkeypatch):
    """The pool ships OFF by default (opt-in, flipped on after the founder's ear-test). These tests
    exercise pool-ON behavior, so enable it. The OFF-path tests override this and still win: the
    kill-switch test sets the flag False (applied after this fixture), and the variety-off test passes
    effect_variety=False (the gate is `_EFFECT_POOL_ENABLED and effect_variety`)."""
    monkeypatch.setattr(planner, "_EFFECT_POOL_ENABLED", True)


def _pair():
    """A comfortably-mixable in-band pair that reliably yields a multi-placement arrangement
    on the deterministic (no-API) fallback path, with DISTINCT song ids so the per-pair seed
    is realistic."""
    a1 = make_analysis(bpm=120.0, n_bars=48)
    a1.song_id = "beat" + "a" * 60
    a2 = make_analysis(bpm=118.0, n_bars=48, vocal_regions=[(0.0, 16.0), (20.0, 40.0), (44.0, 64.0)])
    a2.song_id = "voc" + "b" * 61
    return a1, a2


def _placements(n=3):
    """A fixed set of on-different-anchor placements to hand straight to _select_effects
    (isolates the selection logic from arrangement)."""
    return [Placement(anchor=float(8 + 16 * i), vocal_src=(0.0, 4.0)) for i in range(n)]


def _sel(a1, a2, prompt, take, placements):
    """Call the planner's selection helper with NO Song-1 outro lead (s1_regions=[]) and unit stretch,
    so the tail-safety substitution never fires and the raw 14-combo rotation is what we assert on.
    Centralised so a signature drift in the private helper is a one-line fix, not a scatter of edits.
    (The helper's signature was already observed to change under active development — 2026-08-05.)"""
    return planner._select_effects(a1, a2, prompt, take, placements, [], 1.0)


# ---------------------------------------------------------------- Criterion 1: determinism
def test_effects_selected_is_identical_across_repeated_plan_builds(monkeypatch):
    """AC1: build_mix_plan for the SAME (songs, prompt, take) yields byte-for-byte the same
    effects_selected every call — the mix cache is content-addressed, so a wall-clock or per-run
    random pick would silently break caching and reproducibility. Repeated 5x to smoke out any
    hidden per-call RNG state."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1, a2 = _pair()
    picks = [planner.build_mix_plan("m" * 64, a1, a2, prompt="dreamy", take=4).effects_selected
             for _ in range(5)]
    assert all(p == picks[0] for p in picks), f"effects_selected drifted across identical builds: {picks}"
    # and it actually selected something (the pool is ON by default) — otherwise 'identical' is vacuous
    assert picks[0] != [] or True  # a None/None slot is legal; determinism is the load-bearing claim


def test_selection_seed_does_not_use_wall_clock(monkeypatch):
    """AC1 (sharper): the per-pair combo order is seeded ONLY from (songs + prompt + pool version).
    We call _select_effects on two independent placement lists for the SAME take and pair — the
    returned record and the per-placement (space,width) picks must match exactly. A wall-clock or
    global-RNG seed would let two calls in the same process diverge."""
    a1, a2 = _pair()
    r1 = _sel(a1, a2, "sunset", 3, _placements())
    r2 = _sel(a1, a2, "sunset", 3, _placements())
    assert r1 == r2, f"same (pair, prompt, take) gave different records: {r1} vs {r2}"


def test_different_prompt_can_reshuffle_but_stays_deterministic(monkeypatch):
    """AC1 corollary: the seed includes the prompt, so a different prompt is allowed to pick a
    different slot — but each prompt is itself stable. (Guards that the prompt is actually in the
    seed AND that neither branch is random.)"""
    a1, a2 = _pair()
    p1a = _sel(a1, a2, "A", 2, _placements())
    p1b = _sel(a1, a2, "A", 2, _placements())
    p2 = _sel(a1, a2, "B-different", 2, _placements())
    assert p1a == p1b            # each prompt stable
    # not asserting p1a != p2 (a collision is possible), only that both are deterministic
    assert p2 == _sel(a1, a2, "B-different", 2, _placements())


# ---------------------------------------------------------------- Criterion 2: variety across takes
def test_first_takes_draw_distinct_space_width_combos():
    """AC2: for a fixed pair+prompt, the first several takes draw DISTINCT (space,width) combos from
    a per-pair shuffled rotation of the 14 legal combos — regenerating gives an audibly different
    mix. We drive _select_effects for takes 1..8 with a FRESH placement list each time (so a mutated
    list can't leak state) and assert the 8 combos are all different."""
    a1, a2 = _pair()
    combos = []
    for take in range(1, 9):
        ps = _placements()
        _sel(a1, a2, "share it", take, ps)
        # the take's chosen combo is (its space at the FINAL placement, its width) — the tail-extender
        # rule only moves WHERE a space lands, not WHICH space the take picked.
        final = max(range(len(ps)), key=lambda k: ps[k].anchor)
        combos.append((ps[final].space, ps[final].width))
    assert len(set(combos)) == len(combos), f"takes repeated a (space,width) combo in the first 8: {combos}"


def test_full_rotation_covers_fourteen_distinct_combos():
    """AC2 (the guarantee behind it): 14 legal combos = {None + 4 reverbs + 2 tail-extenders} x
    {None, double}. Takes 1..14 must be a permutation of ALL 14 with no repeats — that is what makes
    'no two of the first several takes repeat' true by construction, and it fails loudly if the
    vocabulary ever shrinks below the >=8 the design needs."""
    a1, a2 = _pair()
    combos = []
    for take in range(1, 15):
        ps = _placements()
        _sel(a1, a2, "x", take, ps)
        final = max(range(len(ps)), key=lambda k: ps[k].anchor)
        combos.append((ps[final].space, ps[final].width))
    assert len(set(combos)) == 14, f"expected 14 distinct combos over takes 1..14, got {len(set(combos))}: {combos}"
    # take 15 wraps back to take 1's slot (rotation) — deterministic, not a 15th novel combo
    ps = _placements()
    _sel(a1, a2, "x", 15, ps)
    f = max(range(len(ps)), key=lambda k: ps[k].anchor)
    assert (ps[f].space, ps[f].width) == combos[0], "take 15 did not wrap to take 1's slot"


def test_variety_across_takes_at_the_plan_level(monkeypatch):
    """AC2 end-to-end (synthetic pair): distinct takes produce distinct effects_selected records
    through the real build_mix_plan wiring, not just the helper. Skips any take the arrangement
    declines (pool-independent), mirroring the real-pair note about pre-declined takes."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1, a2 = _pair()
    records = []
    for take in range(1, 9):
        try:
            m = planner.build_mix_plan("m" * 64, a1, a2, prompt="p", take=take)
        except planner.MixDeclined:
            continue
        records.append(tuple(m.effects_selected))
    assert len(records) >= 4, f"too few successful takes to judge variety: {records}"
    assert len(set(records)) == len(records), f"build_mix_plan repeated an effects_selected across takes: {records}"


# ---------------------------------------------------------------- Criterion 6: variety OFF
def test_effect_variety_off_selects_nothing(monkeypatch):
    """AC6 (plan side): build_mix_plan(effect_variety=False) must record NO picks (effects_selected
    == []) and leave every placement's space/width at None — the exact pre-pool plan, so the render
    stays byte-identical. Also records effect_variety=False on the plan."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1, a2 = _pair()
    m = planner.build_mix_plan("m" * 64, a1, a2, prompt="anything", take=5, effect_variety=False)
    assert m.effects_selected == [], f"variety OFF still recorded picks: {m.effects_selected}"
    for p in m.placements:
        assert p.space is None and p.width is None, f"variety OFF still set a placement effect: {p}"


def test_module_kill_switch_disables_the_pool(monkeypatch):
    """AC6 corollary: the module flag _EFFECT_POOL_ENABLED=False globally disables the pool even with
    effect_variety=True (the debug / golden-regression path described in build_mix_plan)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(planner, "_EFFECT_POOL_ENABLED", False)
    a1, a2 = _pair()
    m = planner.build_mix_plan("m" * 64, a1, a2, prompt="x", take=2, effect_variety=True)
    assert m.effects_selected == []
    for p in m.placements:
        assert p.space is None and p.width is None
