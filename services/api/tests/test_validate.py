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
