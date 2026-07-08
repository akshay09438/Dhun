"""Tests for the AI driver's arrangement planning. We exercise the deterministic
fallback (no network) and the wiring of an AI arrangement via a monkeypatched
_ai_arrange — never a real API call.
"""

import pytest

from app.models import Section
from app.planner import fence, llm, plan as planner, validate
from tests.test_fence import make_analysis


def test_fallback_arrangement_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    mix = planner.build_mix_plan("m" * 64, a1, a2)

    assert mix.source == "rules"
    assert mix.placements  # the arrangement drives the plan now
    assert mix.anchor == mix.placements[0].anchor  # scalar mirrors first (M3 back-compat)
    from app.planner import fence

    assert fence.SAFE_STRETCH_LO <= mix.vocal_stretch <= fence.SAFE_STRETCH_HI


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


def test_regenerate_varies_vocal_content_not_just_anchor(monkeypatch):
    """The real complaint: with only one usable vocal slice (the pre-fix behaviour for a
    song whose vocal_regions came up empty), every regenerate reused the SAME short vocal
    excerpt and only the anchor moved. With multiple candidate slices available (the
    sections fallback), different takes must also pull different vocal content at the
    same placement position — not just resettle on a different timestamp."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[], sections=[
        Section(start=0.0, end=16.0, label="verse"),
        Section(start=16.0, end=32.0, label="chorus"),
        Section(start=32.0, end=48.0, label="chorus"),
        Section(start=48.0, end=64.0, label="bridge"),
    ])

    t1 = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    t2 = planner.build_mix_plan("m" * 64, a1, a2, take=2)

    src1 = [p.vocal_src for p in t1.placements]
    src2 = [p.vocal_src for p in t2.placements]
    assert src1 != src2  # genuinely different vocal content, not the same excerpt replayed


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


def test_shaky_song_still_spans_the_whole_song(monkeypatch):
    """Playing safe on a shaky song (<=2 placements) must NOT abandon the whole-song arc.
    The bug: _apply_flourishes trimmed to the FIRST two placements (early + middle), leaving
    the final third silent. Playing safe should keep an early AND a late entry."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=128)  # ~256s long song
    a1.bpm_confidence = 0.3  # shaky -> plays safe with <=2 placements
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    track_end = a1.beats[-1]
    anchors = [p.anchor for p in plan.placements]
    assert len(plan.placements) <= 2                 # still plays safe
    assert min(anchors) <= track_end / 2             # an early entry
    assert max(anchors) >= track_end * 2 / 3         # AND a late entry — the arc is preserved


def test_regenerate_varies_vocal_window_from_a_single_region(monkeypatch):
    """Even with ONE long vocal region (thin analysis, no multiple sections to rotate
    through), consecutive regenerate takes must play a DIFFERENT part of that region — not
    the identical excerpt from the same start every time (the 'every mix must be unique'
    complaint, in its hardest case)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=48)
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[(0.0, 60.0)])  # one long region

    t1 = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    t2 = planner.build_mix_plan("m" * 64, a1, a2, take=2)

    starts1 = [p.vocal_src[0] for p in t1.placements]
    starts2 = [p.vocal_src[0] for p in t2.placements]
    assert starts1 != starts2  # a different chunk of the region, not the same start every take


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


def test_placements_get_a_beatlock_warp(monkeypatch):
    """Every Song-2 placement carries a per-bar warp map that re-locks it to Song 1's beat,
    and the no-overlap guarantee still holds using the warp-aware length."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert all(p.warp for p in plan.placements)  # each placement is beat-locked
    ordered = sorted(plan.placements, key=lambda p: p.anchor)
    for a, b in zip(ordered, ordered[1:]):  # no overlap, measured with the REAL warped length
        assert fence.placement_end(a.anchor, a.vocal_src, plan.vocal_stretch, a.warp) <= b.anchor + 1e-6


def test_no_warp_when_grid_is_missing(monkeypatch):
    """With no downbeats to lock to, placements fall back to the legacy global stretch
    (empty warp) rather than inventing a lock — never worse than before."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=32)
    a1.downbeats = []  # analysis too thin to define bars
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (20.0, 36.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert all(p.warp == [] for p in plan.placements)


def test_ai_midbar_starts_still_pass_the_referee(monkeypatch):
    """F1 regression: an AI arrangement whose vocal slices start mid-bar must NOT be rejected
    by the referee (R7). The warp map re-locks cleanly instead of shifting off the grid."""
    from app.models import Placement
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 40.0)])
    # two placements that SPAN the song (so the arc guard keeps them), each starting mid-bar
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: [
        Placement(anchor=a1.downbeats[8], vocal_src=(3.1, 23.1)),    # 3.1 is between downbeats
        Placement(anchor=a1.downbeats[50], vocal_src=(5.1, 25.1)),   # in the final third
    ])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    validate.assert_plan(plan, a1, a2)  # must NOT raise — the old code raised a R7 ValidationError


def test_loudest_vocal_peak_lands_on_the_biggest_drop(monkeypatch):
    """The house × Bollywood recipe's core move (R1): Song 2's most POWERFUL vocal stretch
    should land on Song 1's biggest DROP — not wherever the rotation happens to put it."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    # Song 1: one clear, biggest drop in the final third (breakdown at bars 36-39, drop at 40).
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95  # bar 40 -> 80.0s is the biggest drop
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    # Song 2: a LOUD vocal peak early (0-16s) and a quiet region later.
    a2e = [0.2] * 32
    for i in range(0, 8):
        a2e[i] = 0.95
    a2 = make_analysis(bpm=118.0, n_bars=32, energy=a2e,
                       vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    drop_place = min(plan.placements, key=lambda p: abs(p.anchor - 80.0))
    assert abs(drop_place.anchor - 80.0) < 2.0   # a placement lands on the biggest drop
    assert drop_place.vocal_src[0] == 0.0        # ...and it carries Song 2's loudest peak (starts at 0.0)


def test_placement_produce_fields_default_off():
    """The produced-drop fields are additive: old cached plans (no build_bars/echo) still parse."""
    from app.models import Placement
    p = Placement(anchor=1.0, vocal_src=(0.0, 2.0))
    assert p.build_bars == 0 and p.echo is False


def test_drop_placements_are_produced(monkeypatch):
    """A placement that lands on a real house drop is PRODUCED: it gets a filter build into it,
    and the climax gets an echo throw — so the drop feels made, not plain."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95  # a big drop at bar 40 -> 80.0s
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    assert any(getattr(p, "build_bars", 0) > 0 for p in plan.placements)  # a build into a drop
    assert any(getattr(p, "echo", False) for p in plan.placements)        # an echo on the climax


def test_produce_drops_suppresses_echo_when_a_song1_vocal_follows():
    """R1 guard (found by adversarial review): the echo tail rings PAST the vocal's dry end, so
    it must never fire when Song 1's own contrast vocal lands in that tail — that would be two
    lead voices, and the referee can't see the echo tail. Suppress the echo in that case."""
    from app.models import Placement
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 8.0)),
                  Placement(anchor=80.0, vocal_src=(0.0, 8.0))]  # dry end 88.0 at stretch 1.0
    s1_regions = [(89.0, 95.0)]  # Song 1 answers 1s after the final vocal — inside the echo tail
    out = planner._produce_drops(placements, [10.0, 80.0], s1_regions, 1.0, 120.0)
    assert out[-1].echo is False       # echo suppressed -> no echo-over-contrast R1 breach
    assert out[-1].build_bars > 0      # ...but it's still a produced (built) drop


def test_produce_drops_echoes_when_nothing_follows():
    """When the final drop is the end of the mix (no Song 1 vocal after it), the echo fires."""
    from app.models import Placement
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 8.0)),
                  Placement(anchor=80.0, vocal_src=(0.0, 8.0))]
    out = planner._produce_drops(placements, [10.0, 80.0], [], 1.0, 120.0)
    assert out[-1].echo is True


def test_both_vocals_trade_when_song1_has_a_real_passage(monkeypatch):
    """Step 1: when Song 1 (the house track) has a substantial sung passage in a gap between
    Song 2's placements, it LEADS there — both vocals are present and trade (not Song 1 stripped)."""
    from app.models import Placement
    a1 = make_analysis(bpm=120.0, n_bars=96, vocal_regions=[(60.0, 92.0)])  # FO sings a real 32s passage
    a2 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 20.0)])
    # Der Lagi leads early and late, leaving FO's 60-92 passage in a clean gap between them.
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: [
        Placement(anchor=16.0, vocal_src=(0.0, 12.0)),
        Placement(anchor=140.0, vocal_src=(0.0, 12.0)),
    ])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.s1_vocal_regions                                 # Song 1 leads its own passage
    assert any(60.0 <= s and e <= 92.0 and e - s >= 10.0 for s, e in plan.s1_vocal_regions)  # its real passage


def test_extract_json_tolerates_prose():
    assert llm.extract_json('sure!\n{"placements": []}\nthanks') == {"placements": []}
