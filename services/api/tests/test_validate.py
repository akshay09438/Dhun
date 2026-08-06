"""Tests for the referee — the hard-rule guard on the plan and the finished audio."""

import numpy as np
import pytest
import soundfile as sf

from app.models import MixPlan, Placement, StemMove
from app.planner import validate
from tests.test_fence import make_analysis


def make_plan(anchor=16.0, stretch=1.0, vocal_src=(16.0, 40.0)):
    return MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=stretch, vocal_src=vocal_src, anchor=anchor,
    )


def make_arrangement_plan(placements, stretch=1.0, s1_regions=None):
    return MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
        vocal_stretch=stretch, vocal_src=placements[0].vocal_src,
        anchor=placements[0].anchor, placements=placements,
        s1_vocal_regions=s1_regions or [],
    )


def test_validate_plan_clean():
    a1, a2 = make_analysis(), make_analysis()
    assert validate.validate_plan(make_plan(anchor=16.0), a1, a2) == []


def test_validate_plan_clean_on_a_windowed_plan(monkeypatch):
    """A good-parts WINDOWED plan has window-relative (0-based) anchors/warp/moves. The referee is
    handed the FULL Song-1 grid (as the real pipeline does — mix.py passes _load_analysis(song1)),
    so it must re-derive the SAME windowed grid the planner used before judging on-beat/warp/moves.
    Without that, on a real (non-uniform) grid every windowed mix is falsely rejected as off-beat.
    A deterministic drifting grid reproduces it without touching the cache.

    The good-parts window is disabled by default (founder decision 2026-07-09: full-song mixes), so
    this test flips the flag back ON to keep the referee's window-handling covered — the machinery is
    dormant, not deleted, so a future re-enable must still validate cleanly."""
    import os

    from app.models import Section, TrackAnalysis
    from app.planner.plan import build_mix_plan

    monkeypatch.setattr("app.planner.plan._GOOD_PARTS_WINDOW_ENABLED", True)  # exercise the dormant window path
    os.environ.pop("ANTHROPIC_API_KEY", None)  # force the deterministic rules path
    downs, t = [], 0.0
    for i in range(160):  # bar interval drifts 2.00 -> ~2.13s (a real tempo wobble)
        downs.append(round(t, 4)); t += 2.0 + 0.0008 * i
    beats, tb = [], 0.0
    for i in range(len(downs) * 4):
        step = (2.0 + 0.0008 * (i // 4)) / 4
        beats.append(round(tb, 4)); tb += step
    energy = [0.9 if d >= 250.0 else 0.2 for d in downs]  # a clear late drop -> a window exists
    a1 = TrackAnalysis(song_id="beat", status="ready", bpm=120.0, bpm_confidence=0.9,
                       beats=beats, downbeats=downs, phrase_starts=downs[::8], energy_curve=energy,
                       sections=[Section(start=0.0, end=downs[-1], label="verse")], vocal_regions=[])
    a2 = TrackAnalysis(song_id="voc", status="ready", bpm=120.0, bpm_confidence=0.9,
                       beats=[round(0.5 * i, 3) for i in range(600)],
                       downbeats=[round(2.0 * i, 3) for i in range(150)],
                       vocal_regions=[(20.0, 60.0), (120.0, 150.0)])

    plan = build_mix_plan("m" * 64, a1, a2)

    assert plan.window is not None                       # the long drifting song is windowed
    assert validate.validate_plan(plan, a1, a2) == []    # ...and validates CLEAN against the full grid


def test_validate_plan_flags_offbeat_entry():
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    v = validate.validate_plan(make_plan(anchor=5.0), a1, a2)
    assert any("R3" in m for m in v)


def test_validate_plan_flags_unsafe_stretch():
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(make_plan(stretch=1.5), a1, a2)
    assert any("B3" in m for m in v)


def test_validate_plan_flags_empty_slice():
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(make_plan(vocal_src=(16.0, 16.0)), a1, a2)
    assert any("slice" in m for m in v)


def test_validate_flags_overlapping_placements():
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    p = [Placement(anchor=16.0, vocal_src=(0.0, 24.0)),  # 24s vocal from 16 -> ends 40
         Placement(anchor=32.0, vocal_src=(0.0, 8.0))]   # enters 32 -> overlaps
    v = validate.validate_plan(make_arrangement_plan(p), a1, a2)
    assert any("overlap" in m.lower() or "R1" in m for m in v)


def test_validate_flags_offbeat_placement():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0)),
         Placement(anchor=33.1, vocal_src=(0.0, 8.0))]  # 33.1 not on a 2s downbeat
    assert any("R3" in m for m in validate.validate_plan(make_arrangement_plan(p), a1, a2))


def test_validate_accepts_clean_arrangement():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0)),
         Placement(anchor=32.0, vocal_src=(0.0, 8.0))]
    assert validate.validate_plan(make_arrangement_plan(p), a1, a2) == []


def test_validate_flags_overlap_only_visible_at_sub_unity_stretch():
    # At stretch 0.93 the 20s vocal from 16.0 really ends at 16 + 20/0.93 ~= 37.5, so a
    # placement at 36.0 overlaps it. The OLD (inverted) math computed 16 + 20*0.93 = 34.6
    # and MISSED it; the fixed referee, using the shared rendered-length math, catches it.
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    p = [Placement(anchor=16.0, vocal_src=(0.0, 20.0)),
         Placement(anchor=36.0, vocal_src=(0.0, 8.0))]
    v = validate.validate_plan(make_arrangement_plan(p, stretch=0.93), a1, a2)
    assert any("R1" in m or "overlap" in m.lower() for m in v)


def test_validate_flags_s1_s2_vocal_overlap():
    # Song 1's own vocal (20-30) overlaps Song 2's placement window (16 -> ~24): two voices.
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0))]
    v = validate.validate_plan(make_arrangement_plan(p, s1_regions=[(20.0, 30.0)]), a1, a2)
    assert any("R1" in m or "overlap" in m.lower() for m in v)


def test_validate_accepts_s1_vocal_in_a_gap():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0))]  # ends ~24
    v = validate.validate_plan(make_arrangement_plan(p, s1_regions=[(30.0, 40.0)]), a1, a2)
    assert v == []  # Song 1's vocal sits cleanly after Song 2's


def test_validate_allows_a_bounded_vocal_crossfade():
    """R1 refinement: Song 1's vocal may run a CROSSFADE-length into Song 2's entry (it fades out
    as Song 2 comes in — a DJ blend, not a clash). Song 1 sings 8-16.5 into Song 2's entry at 16."""
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0))]
    from app.planner.fence import LEAD_XFADE_SECS
    s1 = [(8.0, 16.0 + LEAD_XFADE_SECS)]  # ends exactly a crossfade past the entry
    assert validate.validate_plan(make_arrangement_plan(p, s1_regions=s1), a1, a2) == []


def test_validate_still_flags_overlap_beyond_a_crossfade():
    """More than a crossfade of overlap is two full lead voices clashing — still a violation."""
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0))]
    s1 = [(8.0, 22.0)]  # runs 6s into Song 2's lead — far beyond a crossfade
    v = validate.validate_plan(make_arrangement_plan(p, s1_regions=s1), a1, a2)
    assert any("R1" in m or "overlap" in m.lower() for m in v)


def test_validate_flags_empty_s1_region():
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0))]
    v = validate.validate_plan(make_arrangement_plan(p, s1_regions=[(30.0, 30.0)]), a1, a2)
    assert any("empty" in m.lower() for m in v)


def test_validate_flags_unknown_fx():
    # a typo'd effect the engine doesn't implement would silently do nothing — fail it loudly
    a1, a2 = make_analysis(), make_analysis()
    p = [Placement(anchor=16.0, vocal_src=(0.0, 8.0), fx="sweep-in")]  # hyphen typo
    v = validate.validate_plan(make_arrangement_plan(p), a1, a2)
    assert any("unknown effect" in m.lower() for m in v)


def test_validate_render_clean(tmp_path):
    wav = tmp_path / "ok.wav"
    sf.write(wav, (0.5 * np.sin(np.linspace(0, 100, 44100))).astype("float32"), 44100)
    assert validate.validate_render(wav) == []


def test_validate_render_flags_silence(tmp_path):
    wav = tmp_path / "silent.wav"
    sf.write(wav, np.zeros(44100, dtype="float32"), 44100)
    assert any("silent" in m for m in validate.validate_render(wav))


def test_validate_render_flags_near_silence(tmp_path):
    # 1s that is mostly silence with a stray blip — exact-zero-peak would miss it
    y = np.zeros(44100, dtype="float32")
    y[:100] = 0.8  # ~0.2% audible, well under the 2% floor
    wav = tmp_path / "blip.wav"
    sf.write(wav, y, 44100)
    assert any("silent" in m for m in validate.validate_render(wav))


def test_validate_render_flags_clipping(tmp_path):
    wav = tmp_path / "clip.wav"
    y = np.ones(44100, dtype="float32")  # full-scale -> clipping
    sf.write(wav, y, 44100)
    assert any("clip" in m for m in validate.validate_render(wav))


def test_assert_helpers_raise():
    a1, a2 = make_analysis(), make_analysis()
    with pytest.raises(validate.ValidationError):
        validate.assert_plan(make_plan(stretch=2.0), a1, a2)


# ---------------------------------------------------------------- movable master (bed_stretch)
# The referee must gain two additive behaviours: flag an out-of-band HOUSE stretch (B3), and run
# the on-beat/warp checks against Song 1's grid RESCALED to the plan's tempo (retimed_analysis),
# so a movable-master plan whose anchors sit on the RETIMED downbeats passes — while a genuinely
# off-beat entry on that same retimed grid is still caught. bed_stretch == 1.0 must be untouched.


def test_validate_plan_flags_offband_bed_stretch():
    # A1: the house (Song 1's bed) may only stretch within [1-HOUSE_SLOW_MAX, 1+HOUSE_SPEED_MAX]
    # = [0.96, 1.08]. A bed_stretch of 1.20 (house +20%) is far outside that protected range and
    # must be flagged B3 — a tighter bound than the vocal's SAFE_STRETCH band.
    a1, a2 = make_analysis(), make_analysis()
    plan = make_plan(anchor=16.0)  # anchor clean on the native grid; only the bed is off-band
    plan.bed_stretch = 1.20
    v = validate.validate_plan(plan, a1, a2)
    assert any("B3" in m for m in v)


def test_validate_movable_master_on_retimed_grid_passes():
    # A2: a movable-master plan (bed_stretch 1.05, master 126) whose anchor sits on a RETIMED
    # downbeat must validate cleanly — the referee must internally rescale a1 to the plan's tempo
    # (fence.retimed_analysis) before the R3 on-beat check. On the NATIVE grid this anchor (~15.24s)
    # is 0.76s off the nearest downbeat, so today's referee wrongly flags R3.
    from app.planner import fence
    a1, a2 = make_analysis(), make_analysis()
    master_bpm = 126.0
    a1r = fence.retimed_analysis(a1, master_bpm)
    anchor = a1r.downbeats[8]  # a downbeat on the RETIMED grid (not on the native grid)
    plan = make_plan(anchor=anchor)
    plan.master_bpm = master_bpm
    plan.bed_stretch = 1.05
    assert validate.validate_plan(plan, a1, a2) == []


def test_validate_movable_master_still_catches_offbeat_entry():
    # A3: rescaling must NOT blind the referee to a real off-beat entry. This anchor sits exactly
    # on a NATIVE downbeat (16.0, so today's referee passes it clean), but on the RETIMED grid
    # (master 126) the nearest downbeat is ~15.24s — 0.76s away — so a referee that switched to the
    # retimed grid must flag R3. It fails now (no R3 raised) precisely because that switch is unbuilt.
    from app.planner import fence
    a1, a2 = make_analysis(), make_analysis()
    master_bpm = 126.0
    a1r = fence.retimed_analysis(a1, master_bpm)
    assert min(abs(16.0 - d) for d in a1r.downbeats) > validate.BEAT_TOLERANCE_SECS  # off the retimed grid
    plan = make_plan(anchor=16.0)
    plan.master_bpm = master_bpm
    plan.bed_stretch = 1.05
    v = validate.validate_plan(plan, a1, a2)
    assert any("R3" in m for m in v)


def test_validate_native_plan_unchanged_by_movable_master():
    # A4 (regression guard): an existing native plan (bed_stretch == 1.0, master 120) must validate
    # EXACTLY as before — a clean native plan still returns []. retimed_analysis(a1, 120) is the
    # identity, so this must stay green after the change (proves the movable path is gated on 1.0).
    a1, a2 = make_analysis(), make_analysis()
    plan = make_plan(anchor=16.0)
    plan.bed_stretch = 1.0
    assert validate.validate_plan(plan, a1, a2) == []


def test_validate_flags_inconsistent_master_bpm():
    # ADVERSARIAL-REVIEW REGRESSION (F2): the referee independently checks master_bpm ~= a1.bpm *
    # bed_stretch, so a plan that claims a stretched grid but an incoherent tempo can't slip past it
    # (the referee stays an INDEPENDENT check, not an echo of the plan field it judges).
    a1, a2 = make_analysis(), make_analysis()   # a1.bpm == 120
    plan = make_plan(anchor=16.0)
    plan.bed_stretch = 1.05                      # in the house band...
    plan.master_bpm = 100.0                      # ...but should be ~126 (120 * 1.05); 100 is incoherent
    v = validate.validate_plan(plan, a1, a2)
    assert any("inconsistent" in m.lower() for m in v)


# ---------------------------------------------------------- R7 per-bar warp grip band (WARP_LO/HI)
# The per-bar beat-lock re-locks each Song-2 vocal bar onto Song 1's downbeat grid. Its PER-BAR
# stretch ratio must be judged against the WIDER grip band [fence.WARP_LO, fence.WARP_HI] =
# [0.85, 1.15], NOT the global no-warble band [SAFE_STRETCH_LO, SAFE_STRETCH_HI] = [0.89, 1.11].
# Why wider: a single transient one-bar correction (~1.7s) may excurse past the global edge; the
# alternative — the lock disengaging so the vocal DRIFTS off the beat over a long placement — is
# far worse. The GLOBAL band (vocal_stretch, B3) is UNCHANGED; only this per-bar tolerance widens.
# make_analysis() puts Song-1 downbeats every 2.0s, so out_secs == 2.0 per bar keeps every bar
# boundary on that grid — isolating the RATIO band as the only thing under test.

from app.planner import fence


def _warp_at_ratio(ratio, n_bars=4, out_secs=2.0, src0=16.0):
    """A warp list of n_bars, each a tuple (src_start, src_end, out_secs) with
    (src_end - src_start) / out_secs == ratio and out_secs == a real Song-1 bar (2.0s), so the
    cumulative boundaries land on the 2.0s downbeat grid and ONLY the per-bar ratio is under test."""
    warp = []
    s = src0
    for _ in range(n_bars):
        warp.append((round(s, 4), round(s + ratio * out_secs, 4), out_secs))
        s += ratio * out_secs
    return warp


def _warp_placement(warp):
    """A single placement entering on downbeat 16.0, its vocal slice spanning the warp bars."""
    return Placement(anchor=16.0, vocal_src=(warp[0][0], warp[-1][1]), warp=warp)


def test_r7_warp_ratio_in_lower_grip_zone_passes():
    # AC1: ratio ~0.87 sits in the NEW grip zone [WARP_LO, SAFE_STRETCH_LO). Today it is flagged R7
    # (0.87 < SAFE_STRETCH_LO 0.89); after the band widens to WARP_LO it must PASS. Boundaries are
    # all on the 2.0s grid (out_secs == 2.0), so the ONLY thing that can raise R7 is the ratio band.
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    ratio = (fence.WARP_LO + fence.SAFE_STRETCH_LO) / 2  # 0.87 — inside new band, below old floor
    assert fence.WARP_LO <= ratio < fence.SAFE_STRETCH_LO
    p = _warp_placement(_warp_at_ratio(ratio))
    v = validate.validate_plan(make_arrangement_plan([p]), a1, a2)
    assert not any("R7" in m for m in v), v


def test_r7_warp_ratio_below_grip_floor_still_flagged():
    # AC2: ratio ~0.80 is BELOW the new floor WARP_LO (0.85) — warble even for a transient bar. It is
    # flagged today AND must stay flagged after the change (this pins that the band WIDENED, not that
    # the R7 ratio check vanished). Regression guard — expected green today.
    a1, a2 = make_analysis(), make_analysis()
    ratio = fence.WARP_LO - 0.05  # 0.80, clearly below the new floor
    p = _warp_placement(_warp_at_ratio(ratio))
    v = validate.validate_plan(make_arrangement_plan([p]), a1, a2)
    assert any("outside the safe stretch band (R7)" in m for m in v), v


def test_r7_warp_ratio_in_upper_grip_zone_passes():
    # AC3 (symmetric): ratio ~1.13 sits in the NEW grip zone (SAFE_STRETCH_HI, WARP_HI]. Flagged
    # today (1.13 > SAFE_STRETCH_HI 1.11); must PASS after the band widens to WARP_HI.
    a1, a2 = make_analysis(), make_analysis()
    ratio = (fence.SAFE_STRETCH_HI + fence.WARP_HI) / 2  # 1.13 — inside new band, above old ceiling
    assert fence.SAFE_STRETCH_HI < ratio <= fence.WARP_HI
    p = _warp_placement(_warp_at_ratio(ratio))
    v = validate.validate_plan(make_arrangement_plan([p]), a1, a2)
    assert not any("R7" in m for m in v), v


def test_r7_warp_ratio_above_grip_ceiling_still_flagged():
    # AC3 (symmetric): ratio ~1.20 is ABOVE the new ceiling WARP_HI (1.15) — still flagged after the
    # change. Regression guard — expected green today.
    a1, a2 = make_analysis(), make_analysis()
    ratio = fence.WARP_HI + 0.05  # 1.20, clearly above the new ceiling
    p = _warp_placement(_warp_at_ratio(ratio))
    v = validate.validate_plan(make_arrangement_plan([p]), a1, a2)
    assert any("outside the safe stretch band (R7)" in m for m in v), v


def test_r7_warp_boundary_off_grid_still_flagged():
    # AC4 (regression): the boundary-on-grid check is UNCHANGED by the widening. Every bar here is in
    # RATIO band (1.0), but the first bar's out_secs is 2.5s, so the interior boundary lands at 18.5s
    # — off Song 1's 2.0s downbeat grid — and must still be flagged R7 as drift, not the ratio band.
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    warp = [(16.0, 18.5, 2.5),   # ratio 2.5/2.5 == 1.0 (in band); boundary at 16.0+2.5 = 18.5 (off grid)
            (18.5, 20.5, 2.0)]   # ratio 2.0/2.0 == 1.0 (in band)
    p = _warp_placement(warp)
    v = validate.validate_plan(make_arrangement_plan([p]), a1, a2)
    assert any("drifted off Song 1's grid (R7)" in m for m in v), v
    assert not any("outside the safe stretch band (R7)" in m for m in v), v  # ratio is in-band; only drift fires


# ---------------------------------------------------------------- Step 3: stem-move referee checks
# validate_plan gains additive checks over every StemMove (the "mixing board" moves). Agreed
# violation-message keywords (each check appends a string CONTAINING the keyword):
#   stem not in {drums,bass,other}        -> "unknown stem"
#   start/end not on a Song-1 downbeat    -> "R3"
#   start >= end (empty/backwards window) -> "empty"
#   gain_from/gain_to outside [0.0, 1.0]  -> "gain"
#   all three bed stems muted at once     -> "mute"
# A valid move adds NO violation. On a movable-master plan (bed_stretch != 1.0) these run against
# the RETIMED grid (fence.retimed_analysis), mirroring the existing R7 warp tests. make_analysis()
# puts Song-1 downbeats every 2.0s, so 16.0/18.0/20.0 are on-grid and 17.1 is off-grid.


def _sm(stem="bass", start=16.0, end=18.0, gain_from=1.0, gain_to=0.0):
    return StemMove(stem=stem, start=start, end=end, gain_from=gain_from, gain_to=gain_to)


def _plan_with_moves(moves, anchor=16.0, bed_stretch=1.0, master_bpm=120.0):
    """A clean single-placement plan (anchor on the 2.0s grid) carrying the given stem moves, so any
    violation the referee raises comes from a stem move — not the base plan."""
    plan = make_plan(anchor=anchor)
    plan.bed_stretch = bed_stretch
    plan.master_bpm = master_bpm
    plan.stem_moves = moves
    return plan


def test_validate_accepts_valid_stem_move():
    # A valid bass pull-and-slam window (both edges on downbeats, gains in [0,1]) adds no violation.
    a1, a2 = make_analysis(), make_analysis()
    assert validate.validate_plan(_plan_with_moves([_sm("bass", 16.0, 18.0, 1.0, 0.0)]), a1, a2) == []


def test_validate_flags_offbeat_stem_move():
    # AC5: a stem move whose edge is off Song 1's downbeat grid (17.1 between the 2.0s downbeats) -> R3.
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(_plan_with_moves([_sm("bass", 16.0, 17.1, 1.0, 0.0)]), a1, a2)
    assert any("R3" in m for m in v), v


def test_validate_flags_unknown_stem():
    # AC5: an unknown stem name would silently do nothing in the engine -> fail it loudly ("unknown stem").
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(_plan_with_moves([_sm("synth", 16.0, 18.0, 1.0, 0.0)]), a1, a2)
    assert any("unknown stem" in m.lower() for m in v), v


def test_validate_flags_stem_move_gain_out_of_range():
    # AC5: v1 allows only duck/mute (gains in [0,1]); a boost (>1.0) or negative gain -> "gain".
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(_plan_with_moves([_sm("bass", 16.0, 18.0, 1.5, 0.0)]), a1, a2)
    assert any("gain" in m.lower() for m in v), v


def test_validate_flags_empty_stem_move_window():
    # AC5: start >= end is an empty/backwards window (both edges on-grid so ONLY "empty" can fire) -> "empty".
    a1, a2 = make_analysis(), make_analysis()
    v = validate.validate_plan(_plan_with_moves([_sm("bass", 18.0, 18.0, 1.0, 0.0)]), a1, a2)
    assert any("empty" in m.lower() for m in v), v


def test_validate_flags_all_three_bed_stems_muted():
    # AC5: defense-in-depth — no instant may have all three bed stems ramped to ~0 (a silent hole).
    # Three hold-muted (0->0) moves over the same on-grid window => at every instant all three are 0.
    a1, a2 = make_analysis(), make_analysis()
    moves = [_sm("drums", 16.0, 18.0, 0.0, 0.0),
             _sm("bass", 16.0, 18.0, 0.0, 0.0),
             _sm("other", 16.0, 18.0, 0.0, 0.0)]
    v = validate.validate_plan(_plan_with_moves(moves), a1, a2)
    assert any("mute" in m.lower() for m in v), v


def test_validate_accepts_two_bed_stems_muted_if_one_stays_audible():
    # The mirror of the guard: muting two bed stems while the third stays up is a legit "just the drums"
    # move and must NOT be flagged (at least one stem audible at every instant).
    a1, a2 = make_analysis(), make_analysis()
    moves = [_sm("bass", 16.0, 18.0, 0.0, 0.0),
             _sm("other", 16.0, 18.0, 0.0, 0.0)]  # drums untouched (stays 1.0)
    v = validate.validate_plan(_plan_with_moves(moves), a1, a2)
    assert not any("mute" in m.lower() for m in v), v


def test_validate_flags_crossing_ramp_silent_hole():
    """Adversarial-review regression (Reviewer 2): the never-all-muted guard must catch a silent hole
    formed by CROSSING ramps, not just constant-0 moves. The exact breach: a bass fade-out, a drums
    fade-in, and a held-0 'other' all sit under the audible floor together for ~74ms — a window a
    coarse 50ms time-sampler could step over. The exact interval-intersection guard catches it. Tested
    on the guard directly with the precise (off-grid) breach geometry, asserting the MUTE flag."""
    moves = [_sm("bass", 6.4, 8.045, 1.0, 0.0),    # fades to 0 by ~8.04
             _sm("drums", 7.955, 9.6, 0.0, 1.0),   # fades up from 0 at ~7.96 — overlaps the bass tail
             _sm("other", 6.4, 9.6, 0.0, 0.0)]      # held silent throughout
    v = validate._stem_move_violations(moves, [round(1.6 * i, 4) for i in range(12)])
    assert any("mute" in m.lower() for m in v), v


def test_validate_flags_stem_move_without_a_grid():
    """Adversarial-review regression (Reviewer 3): a beat move needs a downbeat grid to be on-beat;
    with no grid the R3 check passes vacuously, so the referee flags a moves-without-grid plan. Only
    reachable via a hand-built/corrupt cached plan — the planner only emits moves on a confident grid."""
    v = validate._stem_move_violations([_sm("bass", 2.0, 4.0, 1.0, 0.0)], [])
    assert any("grid" in m.lower() for m in v), v


def test_validate_flags_overlapping_same_stem_moves():
    """Adversarial RE-review regression: the engine MULTIPLIES two overlapping moves on ONE stem, so
    two partial ducks each ABOVE the floor (0.08 > 0.05) can combine into a genuine silent hole the
    min-model muted-span math can't see. The exact breach the re-reviewer rendered: two overlapping
    0.08 ducks on every bed stem => a ~silent window that both the plan guard and the global render
    check passed. Rejecting overlapping same-stem moves closes it (and keeps the guard exact)."""
    a1, a2 = make_analysis(), make_analysis()  # downbeats every 2s
    moves = [_sm("bass", 16.0, 20.0, 0.08, 0.08), _sm("bass", 18.0, 22.0, 0.08, 0.08),      # overlap 18-20
             _sm("drums", 16.0, 20.0, 0.08, 0.08), _sm("drums", 18.0, 22.0, 0.08, 0.08),
             _sm("other", 16.0, 20.0, 0.08, 0.08), _sm("other", 18.0, 22.0, 0.08, 0.08)]
    v = validate.validate_plan(_plan_with_moves(moves), a1, a2)
    assert any("overlap" in m.lower() for m in v), v


def test_validate_accepts_nonoverlapping_same_stem_moves():
    """The normal multi-drop case: two BASS pulls at different drops (windows far apart) is exactly
    what the Wave-1 planner emits — it must NOT be flagged as an overlap."""
    a1, a2 = make_analysis(n_bars=32), make_analysis()  # downbeats 0..62 every 2s
    moves = [_sm("bass", 16.0, 18.0, 1.0, 0.0), _sm("bass", 40.0, 42.0, 1.0, 0.0)]
    v = validate.validate_plan(_plan_with_moves(moves), a1, a2)
    assert not any("overlap" in m.lower() for m in v), v


def test_validate_stem_move_on_retimed_grid_passes():
    # AC6: a movable-master plan (bed_stretch 1.05, master 126) with a stem move on RETIMED downbeats
    # must validate clean — the referee runs the stem-move checks against fence.retimed_analysis, not
    # the native grid. Mirrors test_validate_movable_master_on_retimed_grid_passes.
    a1, a2 = make_analysis(), make_analysis()
    master_bpm = 126.0
    a1r = fence.retimed_analysis(a1, master_bpm)
    anchor, start, end = a1r.downbeats[8], a1r.downbeats[8], a1r.downbeats[10]
    plan = _plan_with_moves([_sm("bass", start, end, 1.0, 0.0)],
                            anchor=anchor, bed_stretch=1.05, master_bpm=master_bpm)
    assert validate.validate_plan(plan, a1, a2) == []


def test_validate_stem_move_off_retimed_grid_flagged():
    # AC6: the same movable-master plan with a stem move on NATIVE downbeats (16.0/18.0) — which are
    # OFF the retimed grid — must be flagged R3. The plan's anchor sits on the RETIMED grid so the ONLY
    # off-grid thing is the stem move. Fails today (no R3) precisely because the retimed stem-move check
    # is unbuilt. Mirrors test_validate_movable_master_still_catches_offbeat_entry.
    a1, a2 = make_analysis(), make_analysis()
    master_bpm = 126.0
    a1r = fence.retimed_analysis(a1, master_bpm)
    assert min(abs(16.0 - d) for d in a1r.downbeats) > validate.BEAT_TOLERANCE_SECS  # 16.0 off the retimed grid
    plan = _plan_with_moves([_sm("bass", 16.0, 18.0, 1.0, 0.0)],
                            anchor=a1r.downbeats[8], bed_stretch=1.05, master_bpm=master_bpm)
    v = validate.validate_plan(plan, a1, a2)
    assert any("R3" in m for m in v), v


# ---------------------------------------------------------------- Phase 0: the vocal chain (P1-P5)
# Each rule has a test that FAILS without the rule (a plan that breaches it must be rejected), plus a
# clean enabled plan that passes. The referee re-derives from the plan's placements/grid; it never
# trusts the move's own numbers. (P2, the pre-master ceiling, is render-side — tested in test_render.py.)

from app.models import DuckMove, VocalProcessMove


def _chain_plan(vmoves=None, dmoves=None):
    """A one-placement plan (anchor 4.0, vocal 0-8 -> ends 12.0 at stretch 1.0) plus chain moves.
    a1 = make_analysis(bpm=120) -> downbeats every 2s, so bar 2 = 4.0s (anchor), bar 6 = 12.0s (end)."""
    return MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64, master_bpm=120.0,
        vocal_stretch=1.0, vocal_src=(0.0, 8.0), anchor=4.0,
        placements=[Placement(anchor=4.0, vocal_src=(0.0, 8.0))],
        vocal_moves=vmoves or [], duck_moves=dmoves or [])


def _good_vm(**k):
    d = dict(placement_id="p0", start_bar=2, end_bar=6, deess=0.4, highpass_hz=90,
             compress_ratio=3.0, saturate_wet=0.25, presence_gain_db=2.5, reverb_wet=0.12)
    d.update(k)
    return VocalProcessMove(**d)


def _a():
    return make_analysis(bpm=120.0, n_bars=16)  # downbeats 0,2,...,30


def test_clean_enabled_chain_plan_passes():
    a1, a2 = _a(), make_analysis()
    assert validate.validate_plan(_chain_plan([_good_vm()], [DuckMove(key_placement_id="p0",
             depth_db=1.5, attack_ms=5, release_ms=120)]), a1, a2) == []


def test_p1_rejects_pitch_beyond_three_semitones():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm(pitch_semitones=5.0)]), a1, a2)
    assert any("P1" in m for m in v), v


def test_p3_rejects_saturate_wet_over_half():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm(saturate_wet=0.7)]), a1, a2)
    assert any("P3" in m for m in v), v


def test_p3_rejects_presence_gain_over_six_db():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm(presence_gain_db=8.0)]), a1, a2)
    assert any("P3" in m for m in v), v


def test_p4_rejects_a_duck_that_boosts():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm()],
            [DuckMove(key_placement_id="p0", depth_db=-2.0, attack_ms=5, release_ms=120)]), a1, a2)
    assert any("P4" in m for m in v), v


def test_p4_rejects_a_duck_deeper_than_six_db():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm()],
            [DuckMove(key_placement_id="p0", depth_db=9.0, attack_ms=5, release_ms=120)]), a1, a2)
    assert any("P4" in m for m in v), v


def test_p4_rejects_a_duck_targeting_the_vocal_stem():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm()],
            [DuckMove(target_stems=["drums", "vocals"], key_placement_id="p0",
                      depth_db=1.5, attack_ms=5, release_ms=120)]), a1, a2)
    assert any("P4" in m for m in v), v


def test_p5_rejects_a_move_that_overlaps_no_placement():
    a1, a2 = _a(), make_analysis()
    # bars 0..1 -> 0.0-2.0s, well before the placement at 4.0-12.0s -> overlaps zero placements
    v = validate.validate_plan(_chain_plan([_good_vm(start_bar=0, end_bar=1)]), a1, a2)
    assert any("P5" in m for m in v), v


def test_p5_rejects_a_move_for_an_unknown_placement():
    a1, a2 = _a(), make_analysis()
    v = validate.validate_plan(_chain_plan([_good_vm(placement_id="p9")]), a1, a2)
    assert any("P5" in m for m in v), v


# ---------------------------------------------------------------- Rule K1: the key-shift referee
# assert_key_shift is the INDEPENDENT correctness check for a key-matched vocal. The pitch helper only
# proves CONSISTENCY (two of its renders agree) — two runs of a buggy engine can agree on WRONG audio —
# so the referee re-derives the chroma of the SHIPPED vocal itself and confirms it rotated by exactly the
# claimed semitones. These tests build synthetic multi-partial tones whose chroma is well-defined and
# shift them in the FREQUENCY domain (partials at MIDI+s), so the shift PROVABLY rotates the chroma by s.
# Fully hermetic: no node, no network, no real Signalsmith helper — just numpy audio on disk.
#
# The two founder-mandated STABLE-BUT-WRONG cases are the whole reason K1 exists: audio that is stable
# (byte-reproducible) but pitched WRONG (or not at all) while labelled key-matched. Each MUST raise.

_K1_SR = 44100
_K1_CHORD = [60, 64, 67, 72]  # C E G C — four distinct pitch classes -> an unambiguous chroma reading


def _k1_tone(tmp_path, name, midis, secs=2.0, sr=_K1_SR):
    """Write a stereo WAV that is a sum of sine partials at the given MIDI notes. Shifting every note by
    s semitones (MIDI+s) rotates the chromagram by exactly s — the ground truth the referee must read."""
    import soundfile as sf
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    mono = np.zeros_like(t)
    for m in midis:
        freq = 440.0 * 2.0 ** ((m - 69) / 12.0)
        mono += np.sin(2 * np.pi * freq * t)
    mono = (0.3 * mono / len(midis)).astype("float32")
    path = tmp_path / name
    sf.write(str(path), np.stack([mono, mono], axis=1), sr)
    return path


def test_k1_raises_when_the_vocal_was_not_shifted_at_all(tmp_path):
    """STABLE-BUT-WRONG (a): an UNSHIFTED vocal labelled semitones=2 MUST raise. This is the exact
    failure the pitch helper cannot catch on its own — it would happily verify two identical un-shifted
    renders as 'consistent' and ship them as key-matched. The referee re-reads the chroma (rotation 0,
    not 2) and declines."""
    orig = _k1_tone(tmp_path, "orig.wav", _K1_CHORD)
    with pytest.raises(validate.ValidationError) as ei:
        validate.assert_key_shift(orig, orig, semitones=2)  # same file -> rotation 0, claimed 2
    assert "K1" in str(ei.value)  # clean, readable decline reason (K1 passes a list, like R1/B3/R7)


def test_k1_raises_when_the_vocal_was_shifted_the_wrong_amount(tmp_path):
    """STABLE-BUT-WRONG (b): a vocal shifted by +3 but LABELLED +2 MUST raise. Stable and really
    pitched — just to the wrong key. The referee reads rotation 3 against the claimed 2 and declines."""
    orig = _k1_tone(tmp_path, "orig.wav", _K1_CHORD)
    shifted_by_3 = _k1_tone(tmp_path, "sh3.wav", [m + 3 for m in _K1_CHORD])
    with pytest.raises(validate.ValidationError) as ei:
        validate.assert_key_shift(orig, shifted_by_3, semitones=2)  # actual +3, claimed +2
    assert "K1" in str(ei.value)  # clean, readable decline reason


def test_k1_passes_a_correctly_shifted_vocal(tmp_path):
    """A vocal genuinely shifted by +2 and labelled +2 must PASS — the referee confirms the chroma
    rotated by exactly the claimed amount, so a real key-match is not falsely declined."""
    orig = _k1_tone(tmp_path, "orig.wav", _K1_CHORD)
    shifted_by_2 = _k1_tone(tmp_path, "sh2.wav", [m + 2 for m in _K1_CHORD])
    validate.assert_key_shift(orig, shifted_by_2, semitones=2)  # must not raise


def test_k1_passes_a_negative_shift(tmp_path):
    """A downward shift is read modulo 12 (a -1 shift is rotation 11). A vocal shifted -1 and labelled
    -1 must PASS — the referee's `semitones % 12` handles the wrap."""
    orig = _k1_tone(tmp_path, "orig.wav", _K1_CHORD)
    shifted_down = _k1_tone(tmp_path, "shm1.wav", [m - 1 for m in _K1_CHORD])
    validate.assert_key_shift(orig, shifted_down, semitones=-1)  # must not raise


def test_k1_passes_when_the_claimed_rotation_is_competitive(monkeypatch, tmp_path):
    """FALSE-REJECT GUARD (reviewer finding): the decisive rule. If the chroma's best pick differs from
    the claim but the CLAIMED rotation is competitive (correlation gap <= _K1_MIN_MARGIN), the material
    is too chroma-flat to judge — K1 must trust the helper's verified render, NOT false-decline a valid
    pair. Driven deterministically via the chroma reading (real chroma-flat vocals produce exactly this)."""
    o, s = _k1_tone(tmp_path, "o.wav", _K1_CHORD), _k1_tone(tmp_path, "s.wav", _K1_CHORD)
    corrs = [0.0] * 12
    corrs[3], corrs[2] = 0.50, 0.50 - validate._K1_MIN_MARGIN + 0.02  # best=3, claim=2 within the margin
    monkeypatch.setattr(validate, "best_rotation", lambda a, b: (3, 0.0, corrs))
    validate.assert_key_shift(o, s, semitones=2)  # inconclusive -> must NOT raise


def test_k1_rejects_a_decisive_wrong_reading(monkeypatch, tmp_path):
    """The other half of the decisive rule: when the chroma DECISIVELY reads a different rotation than
    claimed (claim gap well beyond the margin), that is real stable-but-wrong audio and K1 must decline."""
    o, s = _k1_tone(tmp_path, "o.wav", _K1_CHORD), _k1_tone(tmp_path, "s.wav", _K1_CHORD)
    corrs = [0.0] * 12
    corrs[3], corrs[2] = 0.90, 0.90 - validate._K1_MIN_MARGIN - 0.30  # best=3, claim=2 decisively below
    monkeypatch.setattr(validate, "best_rotation", lambda a, b: (3, 0.0, corrs))
    with pytest.raises(validate.ValidationError):
        validate.assert_key_shift(o, s, semitones=2)  # decisive mismatch -> must raise


def test_k1_is_a_noop_at_zero_semitones(tmp_path):
    """semitones == 0 is a no-op — it must PASS even on identical input (no shift was ever claimed, so
    there is nothing to re-check). Guards that the un-key-matched path is never falsely failed."""
    orig = _k1_tone(tmp_path, "orig.wav", _K1_CHORD)
    validate.assert_key_shift(orig, orig, semitones=0)  # identical input, zero claim -> no raise
