"""Acceptance tests for per-bar beat-lock (the "warp" feature).

The bug this feature fixes: today Song 2's vocal is time-stretched to Song 1's beat
with ONE global FFmpeg atempo ratio for the whole slice. Because real tempo isn't
perfectly constant and BPM detection is imperfect, the vocal drifts off the beat over
a long slice (measured at +315 ms by the end of a 40 s slice on a real pair). The fix
re-locks every bar: chop the vocal at its bar lines and stretch each bar to the
matching Song-1 bar length, so bar boundaries land exactly on Song-1 downbeats and
drift can't accumulate.

These tests are written against the HUMAN-APPROVED CONTRACT, independently of the
implementation. They cover the full public surface end-to-end:
  * models.Placement.warp                (contract 1)
  * fence.warp_map                        (contract 2)
  * fence.placement_end warp param        (contract 3)
  * plan.build_mix_plan attaches warp     (contract 4)
  * validate: warp-aware R1 + new R7      (contract 5)
  * render.render_mix renders the warp    (contract 6)

Several must FAIL now (the feature does not exist yet) and PASS once it is built.
No mocks of the code under test — every assertion checks real behaviour.

workers/ lives at the repo root; put it on the path before importing (matches
test_render.py's bootstrap).
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.models import MixPlan, Placement, TrackAnalysis
from app.planner import fence
from app.planner import plan as planner
from app.planner import validate
from tests.test_fence import make_analysis

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402


# --------------------------------------------------------------------------- #
# Realistic, slightly-irregular beatgrid.                                       #
# A perfect metronome would let a single global ratio stay aligned forever, so  #
# it would hide the drift bug. We jitter each bar a few percent (alternating    #
# long/short) so a single global ratio CANNOT stay locked — that is the real    #
# world this feature exists for.                                                #
# --------------------------------------------------------------------------- #
def _jittered_downbeats(bpm, n_bars, jitter):
    bar = 60.0 / bpm * 4
    t, out = 0.0, []
    for k in range(n_bars):
        out.append(round(t, 4))
        t += bar * (1.0 + (jitter if k % 2 else -jitter))  # alternate long/short bars
    return out


def _drifting_downbeats(bpm, n_bars, per_bar_drift):
    """A realistic grid whose tempo gradually CHANGES (each bar a touch longer than the
    last — a slight ritardando, or imperfect detection). This is the condition the bug
    report describes: over a long slice a single global ratio can't track a moving local
    tempo, so alignment error accumulates MONOTONICALLY (the +315 ms real-world drift).
    """
    bar0 = 60.0 / bpm * 4
    t, out = 0.0, []
    for k in range(n_bars):
        out.append(round(t, 4))
        t += bar0 * (1.0 + per_bar_drift * k)  # bars slowly lengthen -> tempo drifts
    return out


def _grid_analysis(bpm, downbeats, vocal_regions=None):
    """A TrackAnalysis carrying an explicit (possibly irregular) downbeat grid, with
    beats/phrase_starts derived so the fence's fallbacks and runway checks still work."""
    beats = []
    for i, d in enumerate(downbeats):
        nxt = downbeats[i + 1] if i + 1 < len(downbeats) else d + 60.0 / bpm * 4
        for j in range(4):  # 4 beats per bar, evenly split within the (irregular) bar
            beats.append(round(d + (nxt - d) * j / 4, 4))
    return TrackAnalysis(
        song_id="x" * 64, status="ready", bpm=bpm,
        beats=beats, downbeats=list(downbeats), phrase_starts=list(downbeats[::8]),
        energy_curve=[0.5] * len(downbeats), vocal_regions=vocal_regions or [],
    )


# ===========================================================================  #
# CONTRACT 1 — models.Placement.warp (additive optional field)                 #
# ===========================================================================  #
def test_placement_has_warp_field_defaulting_empty():
    p = Placement(anchor=16.0, vocal_src=(0.0, 8.0))
    assert p.warp == []  # additive, optional, empty by default (legacy behaviour)


def test_placement_accepts_warp_list_of_triples():
    p = Placement(anchor=16.0, vocal_src=(0.0, 4.0),
                  warp=[(0.0, 2.0, 1.9), (2.0, 4.0, 2.1)])
    assert len(p.warp) == 2
    src_start, src_end, out_secs = p.warp[0]
    assert (src_start, src_end, out_secs) == (0.0, 2.0, 1.9)


def test_old_plan_without_warp_still_parses():
    # An M3/M4-era cached plan (no warp anywhere) must round-trip unchanged.
    old = {
        "mix_id": "m" * 64, "song1_id": "a" * 64, "song2_id": "b" * 64,
        "master_bpm": 120.0, "vocal_stretch": 1.0, "vocal_src": (16.0, 40.0),
        "anchor": 16.0,
        "placements": [{"anchor": 16.0, "vocal_src": (0.0, 8.0)}],
    }
    plan = MixPlan.model_validate(old)
    assert plan.placements[0].warp == []  # empty warp => legacy global-atempo behaviour


# ===========================================================================  #
# CONTRACT 2 — fence.warp_map                                                   #
# ===========================================================================  #
def test_warp_map_locks_each_bar_boundary_to_song1_downbeats():
    d1 = _jittered_downbeats(122.0, 24, 0.02)  # Song 1 — slightly irregular
    d2 = _jittered_downbeats(125.0, 24, 0.03)  # Song 2 — differently irregular
    anchor = d1[0]
    s0, s1 = d2[0], d2[10]  # a 10-bar vocal slice
    ratio, _ = fence.best_stretch(122.0, 125.0)

    segs = fence.warp_map(anchor, (s0, s1), d1, d2, ratio)

    assert len(segs) >= 2  # a real per-bar map, not a single global segment
    cum = anchor
    for i, (_src_s, _src_e, out_secs) in enumerate(segs):
        cum += out_secs
        nearest = min(d1, key=lambda t: abs(t - cum))
        assert abs(cum - nearest) <= 0.03, f"bar {i} boundary off Song-1 grid by {cum - nearest:.3f}s"


def test_warp_map_sources_are_song2_bars():
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    s0, s1 = d2[0], d2[10]
    segs = fence.warp_map(d1[0], (s0, s1), d1, d2, fence.best_stretch(122.0, 125.0)[0])
    # bar k's source span is (d2[k], d2[k+1]) — the Song-2 bar it re-locks. Allow ~1ms of
    # slack for the contract's rounding of segment times to 3-4 decimals.
    assert abs(segs[0][0] - d2[0]) < 2e-3
    assert abs(segs[0][1] - d2[1]) < 2e-3
    # consecutive bars are contiguous in source time (no gaps, no overlaps)
    for a, b in zip(segs, segs[1:]):
        assert abs(a[1] - b[0]) < 2e-3


def test_warp_map_beats_the_single_global_ratio_drift():
    """The whole point of the feature: per-bar re-lock stays glued to Song-1's grid where
    the OLD single-global-ratio model drifts badly. We use a Song-2 grid whose tempo
    DRIFTS (each bar a touch longer — the real-world condition behind the +315 ms bug), so
    the error a single ratio makes ACCUMULATES bar over bar instead of cancelling out.
    """
    d1 = _jittered_downbeats(122.0, 24, 0.01)          # Song 1: the near-steady master grid
    d2 = _drifting_downbeats(122.0, 24, 0.006)          # Song 2: tempo gradually drifts
    anchor, ratio = d1[0], fence.best_stretch(122.0, 122.0)[0]
    s0, s1 = d2[0], d2[12]                               # a 12-bar slice — long enough to drift

    # OLD model: the whole slice stretched by ONE ratio -> where its last bar boundary lands
    old_end = anchor + (d2[12] - s0) / ratio
    old_drift = abs(old_end - d1[12])

    # NEW model: cumulative warp out_secs from the anchor
    segs = fence.warp_map(anchor, (s0, s1), d1, d2, ratio)
    new_end = anchor + sum(o for _, _, o in segs)
    new_drift = abs(new_end - d1[12])

    assert old_drift > 0.1   # the single ratio drifts more than 100 ms by the end (audible)
    assert new_drift <= 0.03  # per-bar re-lock stays within ~30 ms of Song-1's grid


def test_warp_map_total_length_close_to_global_rendered_length():
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    ratio = fence.best_stretch(122.0, 125.0)[0]
    s0, s1 = d2[0], d2[10]
    segs = fence.warp_map(d1[0], (s0, s1), d1, d2, ratio)
    total_out = sum(o for _, _, o in segs)
    global_len = (s1 - s0) / ratio
    one_bar = 60.0 / 122.0 * 4
    # the warp doesn't grossly change how long the vocal plays (within a bar or so)
    assert abs(total_out - global_len) <= one_bar


def test_warp_map_thin_grid_falls_back_to_single_global_segment():
    # Fewer than 2 downbeats on Song 2's side -> can't chop into bars -> one global segment.
    segs = fence.warp_map(10.0, (0.0, 20.0), [10.0, 12.0, 14.0], [0.0], 0.98)
    assert len(segs) == 1
    src_s, src_e, out_secs = segs[0]
    assert (src_s, src_e) == (0.0, 20.0)
    assert abs(out_secs - 20.0 / 0.98) <= 1e-3  # global-ratio rendered length


def test_warp_map_glitch_bar_falls_back_to_legacy_not_a_warbly_ratio():
    # Inject a missing downbeat -> one double-length Song-2 bar (a grid glitch). CONTRACT
    # (corrected after the F1 safety review): a per-bar global fallback for that one bar would
    # shift every LATER boundary off Song 1's grid, so warp_map instead bails to [] and the
    # placement uses the legacy global stretch. Either way, no warbly ratio ever ships — and
    # whatever it does emit stays inside the safe band.
    d1 = _jittered_downbeats(122.0, 24, 0.02)
    d2 = _jittered_downbeats(125.0, 24, 0.03)
    del d2[5]  # missing downbeat -> a double-length bar around index 4-5
    ratio = fence.best_stretch(122.0, 125.0)[0]
    segs = fence.warp_map(d1[0], (d2[0], d2[10]), d1, d2, ratio)
    assert segs == []  # glitch -> legacy fallback, never a half-locked grid-shifting map
    for src_s, src_e, out_secs in segs:  # vacuous here, but the invariant holds for any output
        assert fence.SAFE_STRETCH_LO - 1e-6 <= (src_e - src_s) / out_secs <= fence.SAFE_STRETCH_HI + 1e-6


# ===========================================================================  #
# CONTRACT 3 — fence.placement_end gains an optional warp param                 #
# ===========================================================================  #
def test_placement_end_with_warp_is_anchor_plus_sum_out_secs():
    warp = [(0.0, 2.0, 1.9), (2.0, 4.0, 2.1)]  # total out = 4.0
    assert abs(fence.placement_end(10.0, (0.0, 4.0), 0.98, warp) - 14.0) < 1e-9


def test_placement_end_without_warp_matches_old_formula():
    # No warp -> unchanged: anchor + (src / stretch). Existing callers must be identical.
    expected = 10.0 + (4.0 - 0.0) / 0.95
    assert abs(fence.placement_end(10.0, (0.0, 4.0), 0.95) - expected) < 1e-9
    assert fence.placement_end(10.0, (0.0, 4.0), 1.0) == 14.0


# ===========================================================================  #
# CONTRACT 4 — plan.build_mix_plan attaches a warp map to each placement        #
# ===========================================================================  #
def test_build_mix_plan_attaches_nonempty_warp_to_every_placement(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # deterministic
    d1 = _jittered_downbeats(122.0, 48, 0.02)
    d2 = _jittered_downbeats(120.0, 48, 0.03)
    a1 = _grid_analysis(122.0, d1)
    a2 = _grid_analysis(120.0, d2, vocal_regions=[(d2[2], d2[14]), (d2[20], d2[32])])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.placements
    for p in plan.placements:
        assert p.warp, "every Song-2 vocal placement must carry a warp map when both grids are usable"


def test_build_mix_plan_warp_boundaries_lock_to_song1_downbeats(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    d1 = _jittered_downbeats(122.0, 48, 0.02)
    d2 = _jittered_downbeats(120.0, 48, 0.03)
    a1 = _grid_analysis(122.0, d1)
    a2 = _grid_analysis(120.0, d2, vocal_regions=[(d2[2], d2[14]), (d2[20], d2[32])])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    for p in plan.placements:
        cum = p.anchor
        for (_s, _e, out_secs) in p.warp:
            cum += out_secs
            nearest = min(d1, key=lambda t: abs(t - cum))
            assert abs(cum - nearest) <= validate.BEAT_TOLERANCE_SECS + 0.03


def test_build_mix_plan_no_overlap_holds_with_warp_aware_end(monkeypatch):
    # R1 (one voice at a time) must still hold when the real end is measured through the warp.
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    d1 = _jittered_downbeats(122.0, 48, 0.02)
    d2 = _jittered_downbeats(120.0, 48, 0.03)
    a1 = _grid_analysis(122.0, d1)
    a2 = _grid_analysis(120.0, d2, vocal_regions=[(d2[2], d2[14]), (d2[20], d2[32])])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    ordered = sorted(plan.placements, key=lambda p: p.anchor)
    for a, b in zip(ordered, ordered[1:]):
        end = fence.placement_end(a.anchor, a.vocal_src, plan.vocal_stretch, a.warp)
        assert end <= b.anchor + 1e-6, "warped placements must not overlap"


# ===========================================================================  #
# CONTRACT 5 — validate: warp-aware R1 + new R7                                 #
# ===========================================================================  #
def _clean_warp(anchor, downbeats, n_bars):
    """A warp whose bar boundaries land exactly on Song-1 downbeats and whose local
    ratios sit at 1.0 (dead centre of the safe band). src bars are 2s each here."""
    warp = []
    for k in range(n_bars):
        out_secs = downbeats[k + 1] - downbeats[k]  # exact Song-1 bar length from anchor==downbeats[0]
        warp.append((float(2 * k), float(2 * k + out_secs), float(out_secs)))
    return warp


def _warp_plan(placements, stretch=1.0):
    return MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
        vocal_stretch=stretch, vocal_src=placements[0].vocal_src,
        anchor=placements[0].anchor, placements=placements,
    )


def test_validate_accepts_clean_warped_plan():
    a1 = make_analysis(bpm=120.0, n_bars=64)  # perfect 2s bars, downbeats at 0,2,4,...
    a2 = make_analysis(bpm=120.0)
    warp = _clean_warp(16.0, a1.downbeats[8:], 4)  # anchor 16.0 == downbeat index 8
    total = sum(o for _, _, o in warp)
    p = Placement(anchor=16.0, vocal_src=(warp[0][0], warp[-1][1]), warp=warp)
    # sanity: the placement really ends where the warp says
    assert abs(fence.placement_end(16.0, p.vocal_src, 1.0, warp) - (16.0 + total)) < 1e-6
    assert validate.validate_plan(_warp_plan([p]), a1, a2) == []


def test_validate_flags_warp_with_out_of_band_ratio():
    # R7: a per-bar local ratio outside [SAFE_STRETCH_LO, SAFE_STRETCH_HI] is a violation.
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=120.0)
    # a 2s source bar squeezed into 1.0s of output -> local ratio 2.0, far above SAFE_STRETCH_HI
    warp = [(0.0, 2.0, 2.0), (2.0, 4.0, 1.0)]  # second bar ratio 2.0 = out of band
    p = Placement(anchor=16.0, vocal_src=(0.0, 4.0), warp=warp)
    v = validate.validate_plan(_warp_plan([p]), a1, a2)
    assert any("R7" in m or "band" in m.lower() or "ratio" in m.lower() for m in v)


def test_validate_flags_warp_boundary_off_the_song1_grid():
    # R7: bar boundaries must lock to Song-1 downbeats within BEAT_TOLERANCE_SECS.
    a1 = make_analysis(bpm=120.0, n_bars=64)  # downbeats at 0,2,4,...
    a2 = make_analysis(bpm=120.0)
    # each bar's out_secs = 1.3s so cumulative boundaries (17.3, 18.6, ...) fall between
    # Song-1 downbeats — off the grid — while local ratios stay in band (2.0s src / 1.3 ~ 1.5?).
    # keep ratio in-band by using a 1.3s source bar too, so ONLY the grid rule can trip.
    warp = [(0.0, 1.3, 1.3), (1.3, 2.6, 1.3), (2.6, 3.9, 1.3)]
    p = Placement(anchor=16.0, vocal_src=(0.0, 3.9), warp=warp)
    v = validate.validate_plan(_warp_plan([p]), a1, a2)
    assert any("R7" in m or "grid" in m.lower() or "downbeat" in m.lower() or "lock" in m.lower()
               for m in v)


def test_validate_flags_overlap_only_visible_through_warp_aware_end():
    """R1 must measure a warped vocal's real end through the warp, not the legacy source
    length. Here the LEGACY end would clear the next entry (no overlap), but the warp
    stretches the vocal long enough to collide — so this fails against a referee still
    using the old (src/stretch) end and passes only with the warp-aware R1.
    """
    a1 = make_analysis(bpm=120.0, n_bars=64)  # downbeats every 2s
    a2 = make_analysis(bpm=120.0)
    # First placement at 16.0: a SHORT 2s source slice (legacy end = 16 + 2/1.0 = 18.0, which
    # clears the next entry at 20.0 -> legacy math sees NO overlap). But its warp stretches
    # those 2s into 6s of output (ends 22.0), so it really runs past 20.0 -> overlap.
    warp1 = [(0.0, 1.0, 3.0), (1.0, 2.0, 3.0)]  # 2s source -> 6.0s output, ends 22.0
    p1 = Placement(anchor=16.0, vocal_src=(0.0, 2.0), warp=warp1)
    legacy_end = fence.placement_end(16.0, (0.0, 2.0), 1.0)  # no warp -> 18.0
    assert legacy_end < 20.0, "guard: legacy end must NOT overlap, so only warp-aware R1 can catch it"
    p2 = Placement(anchor=20.0, vocal_src=(0.0, 4.0),
                   warp=[(0.0, 2.0, 2.0), (2.0, 4.0, 2.0)])
    v = validate.validate_plan(_warp_plan([p1, p2]), a1, a2)
    assert any("R1" in m or "overlap" in m.lower() for m in v)


# ===========================================================================  #
# CONTRACT 6 — render.render_mix renders the warp                              #
# ===========================================================================  #
def _tone(path, freq=220.0, secs=8.0, amp=0.4, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=12.0)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=12.0)
    return paths, vocal


def _render_plan(placements, stretch=1.0):
    return MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
        vocal_stretch=stretch, vocal_src=placements[0].vocal_src,
        anchor=placements[0].anchor, placements=placements,
    )


def test_render_warped_placement_produces_valid_nonclipping_wav(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # 3 bars: source 2s each stretched to 1.9 / 2.0 / 2.1 out-secs (per-bar re-lock)
    warp = [(0.0, 2.0, 1.9), (2.0, 4.0, 2.0), (4.0, 6.0, 2.1)]
    p = Placement(anchor=2.0, vocal_src=(0.0, 6.0), warp=warp)
    render.render_mix(_render_plan([p]), stems, vocal, out)

    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == render.SR
    assert y.shape[1] == 2
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING  # audible, never clipping
    # the finished WAV must still pass the referee's render check
    assert validate.validate_render(out) == []


def test_render_warped_vocal_length_matches_sum_of_out_secs(tmp_path):
    """The rendered vocal must span ~sum(out_secs), NOT the legacy (src/stretch) length.

    We choose a warp whose total output (~6.0s) is MUCH longer than the legacy rendered
    length of vocal_src ((3.0-0.0)/1.0 = 3.0s). A render that ignores the warp and stretches
    the whole slice by the global ratio would fill only ~3s of vocal, leaving [anchor+3.5,
    anchor+5.5] beat-only — so this assertion fails against a warp-ignoring engine and
    passes only when each bar was really re-stretched to its out_secs.
    """
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # 3 source bars of 1.0s each, each stretched to ~2.0s of output -> total ~6.0s
    warp = [(0.0, 1.0, 2.0), (1.0, 2.0, 2.0), (2.0, 3.0, 2.0)]  # total 6.0s
    total_out = sum(o for _, _, o in warp)
    anchor = 2.0
    p = Placement(anchor=anchor, vocal_src=(0.0, 3.0), warp=warp)  # legacy len would be 3.0s
    render.render_mix(_render_plan([p]), stems, vocal, out)

    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    beat_only = e(0.2, 1.8)  # the pure-bed stretch before the vocal enters, as a baseline
    # the LATE part of the warped vocal (well past the 3s legacy length) must still carry
    # clear vocal energy above the beat-only bed -> proves ~6s of vocal was rendered
    late_vocal = e(anchor + 4.0, anchor + 5.8)
    assert late_vocal > beat_only * 1.15, "vocal must still be sounding past the legacy length"
    # and the bed must actually reach anchor + sum(out_secs) of audio
    assert len(y) / sr >= anchor + total_out - 0.05


def test_render_empty_warp_matches_legacy_render(tmp_path):
    # Back-compat: warp=[] must render exactly as the old global-atempo path.
    stems, vocal = _stems(tmp_path)
    legacy_out = tmp_path / "legacy.wav"
    warp_out = tmp_path / "warp_empty.wav"

    legacy = Placement(anchor=2.0, vocal_src=(0.0, 3.0))              # no warp field set
    warp_empty = Placement(anchor=2.0, vocal_src=(0.0, 3.0), warp=[])  # explicit empty warp

    render.render_mix(_render_plan([legacy]), stems, vocal, legacy_out)
    render.render_mix(_render_plan([warp_empty]), stems, vocal, warp_out)

    a, _ = sf.read(legacy_out, dtype="float32", always_2d=True)
    b, _ = sf.read(warp_out, dtype="float32", always_2d=True)
    assert a.shape == b.shape
    assert np.allclose(a, b, atol=1e-6), "empty warp must be byte-identical to legacy render"
