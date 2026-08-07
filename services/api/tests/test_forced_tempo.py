"""Forced tempo auto-match — the 'never decline a far-apart pair' base rule (founder 2026-08-07).

Covers the guardrail the adversarial reviewer flagged as untested: the octave-fold now bounds the
forced stretch for ANY pair, the forced path never declines and stays in the forced band, the flag
OFF is unchanged, and a forced placement is genuinely per-bar beat-locked (multi-segment warp), not a
single global stretch that could drift.
"""
from app.models import KeyInfo, TrackAnalysis
from app.planner import fence, plan


def make_analysis(bpm=120.0, n_bars=48, key="8A", vocal_regions=None):
    beat = 60.0 / bpm
    beats = [round(i * beat, 3) for i in range(n_bars * 4)]
    downbeats = beats[::4]
    return TrackAnalysis(
        song_id="x" * 64, status="ready", bpm=bpm, beats=beats,
        downbeats=downbeats, phrase_starts=downbeats[::8],
        key=KeyInfo(camelot=key, tonic="A", mode="minor", confidence=0.7),
        sections=[], energy_curve=[0.5] * len(downbeats), vocal_regions=vocal_regions or [],
    )


# ---- Finding 3: octave fold must bound the forced stretch for ANY pair -----------------------------

def test_fold_source_multi_octave_keeps_forced_stretch_in_band():
    for master, src in [(200, 60), (60, 200), (128, 74), (90, 180), (174, 87), (200, 65)]:
        folded = fence._fold_source(master, src)
        assert master / 1.4143 - 1e-6 <= folded <= master * 1.4143 + 1e-6, (master, src, folded)
        stretch = round(master / folded, 4)
        assert fence.FORCE_STRETCH_LO <= stretch <= fence.FORCE_STRETCH_HI, (master, src, stretch)


def test_fold_source_unchanged_within_an_octave():
    # for octave-adjacent pairs the new fold equals the old x0.5/x1/x2 nearest — behaviour-preserving
    for master, src in [(120, 95), (120, 70), (128, 140), (100, 55), (120, 122)]:
        old = min((src, src * 2, src / 2), key=lambda b: abs(b - master))
        assert abs(fence._fold_source(master, src) - old) < 1e-6, (master, src)


# ---- never decline; flag gating -------------------------------------------------------------------

def test_flag_off_declines_far_apart_pair():
    a1 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 90.0)])
    a2 = make_analysis(bpm=95.0, vocal_regions=[(0.0, 90.0)])
    assert fence.arrangement_options(a1, a2, force_tempo=False)["mixable"] is False


def test_forced_never_declines_and_stays_in_band():
    a1 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 90.0)])
    a2 = make_analysis(bpm=95.0, vocal_regions=[(0.0, 90.0)])
    o = fence.arrangement_options(a1, a2, force_tempo=True)
    assert o["mixable"] and o["tempo_forced"]
    assert o["master_bpm"] == 120.0 and o["bed_stretch"] == 1.0     # beat stays master, native
    assert fence.FORCE_STRETCH_LO <= o["vocal_stretch"] <= fence.FORCE_STRETCH_HI


def test_forced_extreme_pair_two_octaves_apart_still_mixes():
    a1 = make_analysis(bpm=180.0, vocal_regions=[(0.0, 90.0)])
    a2 = make_analysis(bpm=62.0, vocal_regions=[(0.0, 90.0)])     # ~2.9x apart before folding
    o = fence.arrangement_options(a1, a2, force_tempo=True)
    assert o["mixable"] and o["tempo_forced"]
    assert fence.FORCE_STRETCH_LO <= o["vocal_stretch"] <= fence.FORCE_STRETCH_HI


def test_close_pair_is_not_forced():
    a1 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 90.0)])
    a2 = make_analysis(bpm=122.0, vocal_regions=[(0.0, 90.0)])
    o = fence.arrangement_options(a1, a2, force_tempo=True)
    assert o["mixable"] and not o["tempo_forced"]                  # safe band -> normal path, not forced


# ---- Finding 1: a forced placement must be per-bar beat-locked (multi-segment), not one global stretch

def test_forced_placement_is_beat_locked_multisegment(monkeypatch):
    monkeypatch.setattr(plan, "_FORCE_TEMPO_ENABLED", True)
    a1 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 90.0)])
    a2 = make_analysis(bpm=95.0, vocal_regions=[(0.0, 90.0)])
    p = plan.build_mix_plan("t", a1, a2, rule=1)
    assert p.tempo_forced
    assert p.placements, "forced plan must still place the vocal"
    for pl in p.placements:
        # a real forced placement locks bar-by-bar: its warp has interior boundaries (>1 segment),
        # each of which warp_map pins to a Song-1 downbeat -> no single-global-stretch drift.
        assert pl.warp and len(pl.warp) > 1, f"forced placement not per-bar locked: {pl.warp}"
