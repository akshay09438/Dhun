"""Tests for the referee — the hard-rule guard on the plan and the finished audio."""

import numpy as np
import pytest
import soundfile as sf

from app.models import MixPlan, Placement
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
