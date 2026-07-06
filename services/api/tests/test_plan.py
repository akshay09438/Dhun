"""Tests for the AI driver's arrangement planning. We exercise the deterministic
fallback (no network) and the wiring of an AI arrangement via a monkeypatched
_ai_arrange — never a real API call.
"""

import pytest

from app.planner import fence, plan as planner
from tests.test_fence import make_analysis


def test_fallback_arrangement_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    mix = planner.build_mix_plan("m" * 64, a1, a2)

    assert mix.source == "rules"
    assert mix.placements  # the arrangement drives the plan now
    assert mix.anchor == mix.placements[0].anchor  # scalar mirrors first (M3 back-compat)
    assert 0.92 <= mix.vocal_stretch <= 1.08


def test_arrangement_has_multiple_nonoverlapping_placements(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # force fallback
    energy = [0.3] * 32
    for i in range(0, 8):
        energy[i] = 0.8
    for i in range(16, 24):
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (20.0, 36.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert len(plan.placements) >= 2
    ordered = sorted(plan.placements, key=lambda p: p.anchor)
    for a, b in zip(ordered, ordered[1:]):  # no two vocals overlap (REAL rendered length)
        assert fence.placement_end(a.anchor, a.vocal_src, plan.vocal_stretch) <= b.anchor + 1e-6


def test_no_overlap_when_vocal_is_faster_than_beat(monkeypatch):
    # Song 2 faster than Song 1 -> stretch < 1 -> the vocal plays LONGER. The earlier
    # bug used the inverted math and placed the next entry too soon (two voices at once).
    # This asserts spacing with the REAL rendered length; it fails against that bug.
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=100.0, n_bars=32)
    a2 = make_analysis(bpm=108.0, vocal_regions=[(0.0, 20.0), (24.0, 44.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.vocal_stretch < 1.0  # the harmful direction
    ordered = sorted(plan.placements, key=lambda p: p.anchor)
    for a, b in zip(ordered, ordered[1:]):
        assert fence.placement_end(a.anchor, a.vocal_src, plan.vocal_stretch) <= b.anchor + 1e-6


def test_regenerate_yields_a_different_arrangement(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.5] * 32
    for i in (4, 12, 20, 28):
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=32, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 12.0), (16.0, 28.0)])

    t1 = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    t2 = planner.build_mix_plan("m" * 64, a1, a2, take=2)

    assert [p.anchor for p in t1.placements] != [p.anchor for p in t2.placements]


def test_ai_arrangement_is_used_when_available(monkeypatch):
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    from app.models import Placement
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: [
        Placement(anchor=16.0, vocal_src=(16.0, 24.0)),
        Placement(anchor=48.0, vocal_src=(16.0, 24.0), beat_breath=True),
    ])

    mix = planner.build_mix_plan("m" * 64, a1, a2, prompt="build it up")
    assert mix.source == "ai"
    assert len(mix.placements) == 2 and mix.placements[1].beat_breath is True


def test_contrast_and_sweep_on_a_confident_pair(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(60.0, 90.0)])  # S1 sings in a gap
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (30.0, 50.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.s1_vocal_regions  # Song 1's own vocal answers in a gap
    assert sum(1 for p in plan.placements if p.fx == "sweep_in") == 1  # one subtle sweep


def test_shaky_song_plays_safe(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(60.0, 90.0)])
    a1.bpm_confidence = 0.3  # loose grid — don't risk the fancy moves
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (30.0, 50.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert len(plan.placements) <= 2
    assert plan.s1_vocal_regions == []
    assert all(p.fx is None and p.beat_breath is False for p in plan.placements)


def test_declines_when_unmixable():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    with pytest.raises(planner.MixDeclined) as exc:
        planner.build_mix_plan("m" * 64, a1, a2)
    assert "tempo" in str(exc.value).lower()


def test_long_song_vocal_spans_the_whole_song(monkeypatch):
    """The arc fix: on a long song with its loud sections in the middle, the vocal must
    still reach the first half AND the final third — not clump in the middle (the
    founder's actual complaint on a 7-minute song)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # deterministic
    energy = [0.3] * 128
    for i in range(56, 72):  # loudest sections are in the middle — the clustering trap
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=128, energy=energy)  # ~256s (~4.3 min)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    track_end = a1.beats[-1]
    anchors = [p.anchor for p in plan.placements]
    assert min(anchors) <= track_end / 2       # a vocal in the first half (no empty start)
    assert max(anchors) >= track_end * 2 / 3    # a strong entry in the final third


def test_clustered_ai_arrangement_is_spread_by_the_guard(monkeypatch):
    """Even if the AI clusters every vocal in the middle, the arc guard rebuilds a spread
    arrangement so the song never has an empty half."""
    from app.models import Placement
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: [
        Placement(anchor=120.0, vocal_src=(0.0, 20.0)),   # all three bunched
        Placement(anchor=145.0, vocal_src=(0.0, 20.0)),    # around the middle
        Placement(anchor=170.0, vocal_src=(0.0, 20.0)),    # of a ~256s track
    ])
    a1 = make_analysis(bpm=120.0, n_bars=128)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    track_end = a1.beats[-1]
    anchors = [p.anchor for p in plan.placements]
    assert min(anchors) <= track_end / 2
    assert max(anchors) >= track_end * 2 / 3
    assert plan.source == "rules"  # the guard replaced the clustered AI plan


def test_extract_json_tolerates_prose():
    assert planner._extract_json('sure!\n{"placements": []}\nthanks') == {"placements": []}
