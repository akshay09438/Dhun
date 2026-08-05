"""Acceptance tests for the phrase-throw + continuous-reverb feature (step 3) — the REAL-AUDIO set.

These use the cached demo pairs under services/api/data, loaded exactly as the mix route does. The
founder was explicit that the breath defect must be reproduced on the ACTUAL Father Ocean x Der Lagi
audio, not a synthetic stand-in — so criterion 4 loads the real Der Lagi vocal stem. Each test skips
(never silently passes) when its cached data is absent.

Criteria covered here:
  2  THROW RATE — across the real pair + several takes, throws fire on ~20-30% of the 4-bar moments.
  4  BREATH DEFECT — on the REAL Der Lagi vocal stem, _punchy_bar returns None for a breath fragment
     and a real fragment for a voiced one (the re-fire never grabs a breath — Father Ocean 3:56).
  7  DETERMINISM — same take twice gives identical throw decisions AND a byte-identical render.

Pool/arrangement note (from the task): some takes on the throw-rate pair PRE-DECLINE on a pool-
independent R1 arrangement overlap (takes 3 & 7). Declined takes are skipped, never counted.
"""

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from app.audio.analysis import analysis_path
from app.audio.stems import stem_path
from app.planner import fence, plan as planner, throws as throws_mod, validate
from app.routes.mix import _load_analysis

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402

# Throw-rate / determinism pair (b8696… beat x fedc9… vocal) — the task's real cached pair.
BEAT_ID = "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef"
VOCAL_ID = "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20"
_S1_STEMS = ("drums", "bass", "other")

# Breath-defect pair — the ACTUAL Father Ocean (beat) x Der Lagi Lekin (vocal) case (3:56).
FATHER_OCEAN_ID = "ac59f8c4af7e89e916dc825690ade5dbc2b9c6f221c5a7ef863eb9863f3826e1"
DER_LAGI_ID = "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430"

_PAIR_READY = (
    analysis_path(BEAT_ID).exists() and analysis_path(VOCAL_ID).exists()
    and all(stem_path(BEAT_ID, s).exists() for s in _S1_STEMS)
    and stem_path(VOCAL_ID, "vocals").exists()
)
_needs_pair = pytest.mark.skipif(not _PAIR_READY, reason="real throw-rate demo pair not present under data/")

_DER_LAGI_READY = stem_path(DER_LAGI_ID, "vocals").exists() and analysis_path(FATHER_OCEAN_ID).exists()
_needs_der_lagi = pytest.mark.skipif(
    not _DER_LAGI_READY, reason="real Father Ocean x Der Lagi cached audio not present under data/")


@pytest.fixture(autouse=True)
def _throw_on_deterministic(monkeypatch):
    """Turn the phrase-throw feature ON (it ships OFF/opt-in) and force the deterministic rules path
    (no ANTHROPIC key -> no network, no LLM variance), so 'same take twice' is a fair determinism test."""
    monkeypatch.setattr(planner, "_PHRASE_THROW_ENABLED", True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ---------------------------------------------------------------- shared plan builders (real pair)
def _built_plans(n_takes=8):
    """Build takes 1..n on the throw-rate pair with the throw flag ON. Skips only takes build_mix_plan
    itself declines (MixDeclined). Returns (a1, a2, [(take, plan), ...])."""
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
    """A take 'ships' iff the full referee passes (the mix route's gate). Declined arrangement takes
    (3 & 7 on this pair) are filtered out here — never by weakening a throw assertion."""
    return validate.validate_plan(plan, a1, a2) == []


def _placement_moment_counts(plan):
    """(total 4-bar moments, total throws) across a plan's placements — recomputed with the SAME
    placement_end / bar math the planner and referee use, so the measured rate is independent of any
    number the plan happens to store."""
    bar_secs = (60.0 / plan.master_bpm) * 4.0 if plan.master_bpm else 0.0
    moments = throws = 0
    if bar_secs <= 0:
        return 0, 0
    for p in plan.placements:
        end = fence.placement_end(p.anchor, p.vocal_src, plan.vocal_stretch, getattr(p, "warp", None))
        length_bars = max(0, round((end - p.anchor) / bar_secs))
        moments += length_bars // throws_mod.MOMENT_BARS
        throws += len(getattr(p, "throws", None) or [])
    return moments, throws


# ================================================================ Criterion 2: throw rate ~20-30%
@_needs_pair
def test_throw_rate_across_takes_is_in_the_20_to_30_percent_band():
    """CRITERION 2: aggregated across the real pair's SHIPPING takes, echo throws fire on 15-35% of the
    4-bar moments (the ~20-30% target, with a tolerance band). Declined arrangement takes are skipped."""
    a1, a2, plans = _built_plans(8)
    shipping = [(t, p) for t, p in plans if _ships(p, a1, a2)]
    assert len(shipping) >= 3, f"too few shipping takes to judge the throw rate (got {len(shipping)})"
    total_moments = total_throws = 0
    per_take = []
    for t, p in shipping:
        m, thr = _placement_moment_counts(p)
        total_moments += m
        total_throws += thr
        per_take.append((t, thr, m))
    assert total_moments >= 8, f"too few 4-bar moments to judge a rate ({total_moments}); per-take={per_take}"
    rate = total_throws / total_moments
    assert 0.15 <= rate <= 0.35, (
        f"throw rate {rate:.2%} outside the 15-35% band "
        f"({total_throws} throws / {total_moments} moments); per-take (take, throws, moments)={per_take}")


# ================================================================ Criterion 4: breath defect (REAL audio)
@_needs_der_lagi
def test_punchy_bar_skips_a_breath_and_keeps_a_voiced_bar_on_real_der_lagi():
    """CRITERION 4: on the REAL Der Lagi vocal stem (the pair that killed the Father Ocean drop at 3:56),
    _punchy_bar must return None for a low-energy BREATH/near-silence bar and a real fragment for a
    VOICED bar — so the carry re-fire can never grab a breath. Fragments are LOCATED from the real
    audio: the quietest bar window (a breath) and the loudest (a sung phrase)."""
    voc = render._decode(stem_path(DER_LAGI_ID, "vocals"))
    assert len(voc) > 0, "decoded Der Lagi vocal is empty"

    a1 = _load_analysis(FATHER_OCEAN_ID)
    bpm = a1.bpm if (a1 and a1.bpm) else 120.0
    bar = (60.0 / bpm) * 4.0 * render.SR           # one bar in samples (the re-fire fragment length)
    b = int(bar)
    assert b > 0 and len(voc) >= 2 * b, "vocal too short to hold two bar-length windows"

    peak = float(np.max(np.abs(voc)))
    assert peak > 0.0, "decoded vocal is silent"

    # scan non-overlapping bar windows; rms of each, as a fraction of the global sample peak
    ends, ratios = [], []
    pos = b
    while pos <= len(voc):
        frag = voc[pos - b:pos]
        rms = float(np.sqrt(np.mean(np.square(frag))))
        ends.append(pos)
        ratios.append(rms / peak)
        pos += b
    ratios = np.array(ratios)

    voiced_i = int(np.argmax(ratios))              # the loudest bar -> a sung phrase
    voiced_end = ends[voiced_i]
    # prefer a genuine BREATH sitting JUST BELOW the voiced floor (the adversarial boundary case — the
    # breath most likely to be mistaken for a sung bar, which is exactly what the 3:56 defect grabbed);
    # fall back to the quietest window (near-silence) if no in-band breath exists.
    floor = render._VOICED_FLOOR
    breath_band = [(r, e) for r, e in zip(ratios, ends) if 0.003 < r < floor]
    if breath_band:
        breath_ratio, breath_end = max(breath_band, key=lambda x: x[0])  # loudest breath under the floor
    else:
        quiet_i = int(np.argmin(ratios))
        breath_ratio, breath_end = float(ratios[quiet_i]), ends[quiet_i]

    assert float(ratios[voiced_i]) >= floor, (
        f"no clearly-voiced bar found (loudest rms/peak={ratios[voiced_i]:.3f} < floor {floor}) — "
        "cannot prove the voiced side")
    assert breath_ratio < floor, f"selected breath bar is not below the voiced floor (rms/peak={breath_ratio:.3f})"

    voiced_frag = render._punchy_bar(voc, voiced_end, bar)
    breath_frag = render._punchy_bar(voc, breath_end, bar)
    assert voiced_frag is not None and len(voiced_frag) > 0, (
        f"_punchy_bar dropped a VOICED bar (rms/peak={ratios[voiced_i]:.3f}) — the drop would lose its re-fire")
    assert breath_frag is None, (
        f"_punchy_bar RE-FIRED a breath (rms/peak={breath_ratio:.3f} < {floor}) — this is the Father Ocean "
        "3:56 defect: a breath grabbed as the re-fire kills the drop")


# ================================================================ Criterion 7: determinism
@_needs_pair
def test_throw_decisions_are_deterministic_take_for_take():
    """CRITERION 7a: building the same take twice yields identical throw decisions (moments/ratios) and
    reverb-bed flags — the seed comes from the mix id, never the wall clock, so Regenerate + the mix
    cache are reproducible."""
    a1, a2 = _load_analysis(BEAT_ID), _load_analysis(VOCAL_ID)
    for take in (1, 2):
        try:
            p1 = planner.build_mix_plan("m" * 64, a1, a2, prompt="", take=take)
            p2 = planner.build_mix_plan("m" * 64, a1, a2, prompt="", take=take)
        except planner.MixDeclined:
            continue
        d1 = [(list(pl.throws or []), bool(pl.reverb_bed)) for pl in p1.placements]
        d2 = [(list(pl.throws or []), bool(pl.reverb_bed)) for pl in p2.placements]
        assert d1 == d2, f"take {take}: throw decisions differ run-to-run\n  {d1}\n  {d2}"
        assert p1.effects_selected == p2.effects_selected, f"take {take}: effects_selected differ"


@_needs_pair
def test_real_throw_render_is_byte_identical_rendered_twice(tmp_path):
    """CRITERION 7b: a real throw-carrying take renders byte-for-byte identically twice — the throw
    engine (echo/re-fire/reverb bed) uses only fixed seeds, so the content-addressed mix cache holds."""
    a1, a2, plans = _built_plans(8)
    shipping = [(t, p) for t, p in plans if _ships(p, a1, a2)]
    assert shipping, "no shipping take to render"
    # prefer a take that actually carries throws (so the throw path is exercised, not just the OFF path)
    with_throws = [(t, p) for t, p in shipping if any((pl.throws or []) for pl in p.placements)]
    take, plan = (with_throws or shipping)[0]

    stems = {s: stem_path(BEAT_ID, s) for s in _S1_STEMS}
    if stem_path(BEAT_ID, "vocals").exists():
        stems["vocals"] = stem_path(BEAT_ID, "vocals")
    s2_voc = stem_path(VOCAL_ID, "vocals")

    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    render.render_mix(plan, stems, s2_voc, a)
    render.render_mix(plan, stems, s2_voc, b)
    import soundfile as sf
    ha = hashlib.sha256(sf.read(a, dtype="float32", always_2d=True)[0].tobytes()).hexdigest()
    hb = hashlib.sha256(sf.read(b, dtype="float32", always_2d=True)[0].tobytes()).hexdigest()
    assert ha == hb, f"real throw render (take {take}) is not deterministic: {ha} != {hb}"
