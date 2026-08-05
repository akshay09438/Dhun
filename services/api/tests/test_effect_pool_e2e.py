"""End-to-end acceptance tests for the effect pool on the REAL cached demo pair.

Uses the real analyses + stems under services/api/data (loaded exactly as the mix route does)
where a synthetic fixture can't prove the whole plan->referee->render path agrees. Kept lean:
one plan-level variety/referee test (fast) and one real-audio render-determinism test.

Real pair: beat song = b8696…bef, vocal song = fedc9…f20. NOTE (from the task): takes 3 and 7
of this pair PRE-DECLINE on R1 for arrangement reasons unrelated to the pool, so declined takes
are skipped in the variety assertion.

Criteria covered here:
  2 VARIETY ACROSS TAKES — real-pair plans across takes give DISTINCT effects_selected.
  4 (integration) the referee accepts the pool picks the planner actually made on a real arrangement.
  1 DETERMINISM — a real rendered take is byte-identical when rendered twice.
"""

import hashlib
import sys
from pathlib import Path

import pytest
import soundfile as sf

from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.planner import plan as planner, validate
from app.routes.mix import _load_analysis

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers.render import render_mix  # noqa: E402

BEAT_ID = "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef"
VOCAL_ID = "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20"
_S1_STEMS = ("drums", "bass", "other")

_DATA_READY = (
    analysis_path(BEAT_ID).exists() and analysis_path(VOCAL_ID).exists()
    and all(stem_path(BEAT_ID, s).exists() for s in _S1_STEMS)
    and stem_path(VOCAL_ID, "vocals").exists()
)
_needs_data = pytest.mark.skipif(not _DATA_READY, reason="real cached demo pair not present under data/")


@pytest.fixture(autouse=True)
def _pool_on(monkeypatch):
    """The pool ships OFF by default (opt-in); these end-to-end tests verify pool-ON behavior, so
    enable it explicitly. (Determinism/byte-identity still hold with the pool on.) Rule 4 is now LIVE and
    supersedes the pool (its branch runs first in build_mix_plan), so turn Rule 4 OFF to test the pool."""
    monkeypatch.setattr(planner, "_RULE4_ENABLED", False)
    monkeypatch.setattr(planner, "_EFFECT_POOL_ENABLED", True)


def _built_plans(n_takes=8):
    """Build takes 1..n on the real pair. Skips ONLY takes build_mix_plan itself declines (MixDeclined).
    Note: some takes (3 and 7 for this pair) build fine but the REFEREE later rejects them for a
    pool-INDEPENDENT arrangement reason (an R1 Song1/Song2 vocal overlap); those are filtered per-test
    by 'ships' below, never by weakening a pool assertion. Returns (a1, a2, [(take, plan), ...])."""
    a1, a2 = _load_analysis(BEAT_ID), _load_analysis(VOCAL_ID)
    out = []
    for take in range(1, n_takes + 1):
        try:
            p = planner.build_mix_plan("m" * 64, a1, a2, prompt="", take=take)
        except planner.MixDeclined:
            continue
        out.append((take, p))
    return a1, a2, out


def _ships(plan, a1, a2):
    """A take 'ships' iff the full referee passes — the mix route's plan->assert_plan->render gate."""
    return validate.validate_plan(plan, a1, a2) == []


# ---------------------------------------------------------------- Criterion 2 + 4 (real pair)
@_needs_data
def test_real_pair_pool_picks_are_always_referee_clean():
    """AC4 (integration): the planner must NEVER emit an illegal pool pick on the real pair — the
    referee's POOL rules (_pool_violations) pass for EVERY built take, regardless of whether the take's
    ARRANGEMENT later declines. This isolates the pool concern from the pool-independent R1 arrangement
    decline (takes 3 & 7), so an illegal tail-extender placement can't hide behind an arrangement fail."""
    _a1, _a2, plans = _built_plans(14)
    assert plans, "no takes built at all"
    for take, p in plans:
        v = validate._pool_violations(p.placements)
        assert v == [], f"take {take}: planner emitted an illegal pool pick: {v}"


@_needs_data
def test_real_pair_shipping_takes_pick_distinct_combos():
    """AC2: among the takes that actually SHIP (pass the full referee — declined arrangement takes 3 & 7
    are skipped exactly as the task notes), each picks a DISTINCT effects_selected combo, so
    regenerating a shippable mix gives an audibly different result."""
    a1, a2, plans = _built_plans(8)
    shipping = [(t, p) for t, p in plans if _ships(p, a1, a2)]
    assert len(shipping) >= 4, f"too few shipping takes to judge variety (got {len(shipping)})"
    records = [tuple(p.effects_selected) for _, p in shipping]
    assert len(set(records)) == len(records), f"shipping real-pair takes repeated effects_selected: {records}"


@_needs_data
def test_real_pair_tail_extenders_land_only_on_the_final_placement():
    """AC4 (integration): whenever a take's pick is a tail-extender (throw/freeze), the planner places
    it ONLY on the final (max-anchor) placement and nowhere else — the R1 rule the referee enforces,
    verified on the picks the planner actually made across the full 14-combo rotation."""
    _a1, _a2, plans = _built_plans(14)
    saw_tail = False
    for take, p in plans:
        if not p.placements:
            continue
        final = max(range(len(p.placements)), key=lambda k: p.placements[k].anchor)
        for i, pl in enumerate(p.placements):
            if pl.space in ("throw", "freeze"):
                saw_tail = True
                assert i == final, f"take {take}: tail-extender '{pl.space}' on non-final placement {i}"
    # not a hard requirement that a tail appeared in 1..14, but on a 14-combo rotation it should have
    assert saw_tail, "no tail-extender appeared across takes 1..14 — the final-only rule went untested"


# ---------------------------------------------------------------- Criterion 1 (real render)
@_needs_data
def test_real_render_is_byte_identical_rendered_twice(tmp_path):
    """AC1: a real rendered take is byte-for-byte identical when rendered twice — the pool never uses
    wall-clock, so the content-addressed mix cache holds on real audio. Renders the first non-declined
    take twice (mirroring the mix route's stem wiring) and compares decoded samples."""
    a1, a2, plans = _built_plans(8)
    shipping = [(t, p) for t, p in plans if _ships(p, a1, a2)]
    assert shipping, "no shipping take to render"
    take, plan = shipping[0]
    stems = {s: stem_path(BEAT_ID, s) for s in _S1_STEMS}
    s1_voc = stem_path(BEAT_ID, "vocals")
    if s1_voc.exists():
        stems["vocals"] = s1_voc
    s2_voc = stem_path(VOCAL_ID, "vocals")

    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    render_mix(plan, stems, s2_voc, a)
    render_mix(plan, stems, s2_voc, b)
    ha = hashlib.sha256(sf.read(a, dtype="float32", always_2d=True)[0].tobytes()).hexdigest()
    hb = hashlib.sha256(sf.read(b, dtype="float32", always_2d=True)[0].tobytes()).hexdigest()
    assert ha == hb, f"real pooled render (take {take}) is not deterministic: {ha} != {hb}"


@_needs_data
def test_pool_effect_is_audibly_present_in_the_mix(tmp_path):
    """AUDIBILITY (the gap the founder caught 2026-08-05): a pool effect must reach the output at an
    AUDIBLE level, not vanish. Renders a shipping take with the pool ON vs the SAME take/arrangement
    with the pool OFF, and asserts the effect contributes LOUDER than -13 dB below the mix. The pre-fix
    peak-neutral pool sat at -17.6 dB (inaudible) — this test would have FAILED it. (Selection ≠
    execution ≠ audibility; the earlier 34 tests proved the first two but not this.)"""
    import numpy as np

    a1, a2, plans = _built_plans(8)
    stems = {s: stem_path(BEAT_ID, s) for s in _S1_STEMS}
    if stem_path(BEAT_ID, "vocals").exists():
        stems["vocals"] = stem_path(BEAT_ID, "vocals")
    s2_voc = stem_path(VOCAL_ID, "vocals")
    # the shipping take carrying the MOST effects (a space + width stack — the strongest, most robust signal)
    cand = sorted([(t, p) for t, p in plans if _ships(p, a1, a2) and p.effects_selected],
                  key=lambda tp: len(tp[1].effects_selected), reverse=True)
    assert cand, "no shipping take carries a pool effect to test audibility"
    take, on = cand[0]
    off = planner.build_mix_plan("m" * 64, a1, a2, prompt="", take=take, effect_variety=False)
    aw, bw = tmp_path / "on.wav", tmp_path / "off.wav"
    render_mix(on, stems, s2_voc, aw)
    render_mix(off, stems, s2_voc, bw)
    yon = sf.read(aw, dtype="float32", always_2d=True)[0]
    yoff = sf.read(bw, dtype="float32", always_2d=True)[0]
    m = min(len(yon), len(yoff))
    rms = lambda x: float(np.sqrt(np.mean(np.square(x[:m].astype(np.float64)))))  # noqa: E731
    below_db = 20 * np.log10(rms(yon - yoff) / rms(yon))
    assert below_db > -13.0, (f"pool effect {on.effects_selected} is only {below_db:.1f} dB below the mix "
                              f"(<= -13 dB is inaudible — the pre-fix bug); the effect must reach the output audibly")
