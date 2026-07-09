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


def test_build_mix_plan_sets_bed_stretch_and_plans_on_retimed_grid(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # force fallback
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=144.0, n_bars=64, vocal_regions=[(16.0, 40.0)])  # Tere Bina shape
    plan = planner.build_mix_plan("m" * 64, a1, a2)
    assert plan.bed_stretch > 1.0 and plan.master_bpm > 122.0  # house nudged up, movable master
    # every anchor lands on a downbeat of the RETIMED grid (what the audio will play at)
    dg = fence.retimed_analysis(a1, plan.master_bpm).downbeats
    for p in plan.placements:
        assert min(abs(p.anchor - d) for d in dg) <= 0.06


def test_build_mix_plan_in_band_pair_has_unit_bed_stretch(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=122.0, n_bars=64, vocal_regions=[(20.0, 40.0)])
    a2 = make_analysis(bpm=118.0, n_bars=64, vocal_regions=[(16.0, 40.0)])
    assert planner.build_mix_plan("m" * 64, a1, a2).bed_stretch == 1.0


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

    # A different take must yield a genuinely different arrangement. With phrasing, anchors are
    # locked to the 8-bar grid (so two takes can share phrase lines), so the variety shows up in the
    # placements as a whole — a different anchor OR different vocal content at a spot.
    assert [(p.anchor, p.vocal_src) for p in t1.placements] != [(p.anchor, p.vocal_src) for p in t2.placements]


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
    """The produced-drop fields are additive: old cached plans (no build_bars/echo/chop) still parse."""
    from app.models import Placement
    p = Placement(anchor=1.0, vocal_src=(0.0, 2.0))
    assert p.build_bars == 0 and p.echo is False and p.chop is False


def test_vocal_chop_is_parked_but_the_function_still_works(monkeypatch):
    """Step 4 vocal chop is PARKED (founder decision 2026-07-09): the plan flags NO chop, so no mix can
    go dead on a breath. But the dormant _flag_chop_on_biggest_drop still works when called directly —
    so reviving the feature later is a one-line change, and this proves the machinery is intact."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 96
    for i in range(24, 28):
        energy[i] = 0.9   # a solid drop at bar 24 -> 48.0s
    for i in range(60, 64):
        energy[i] = 0.2
    for i in range(64, 72):
        energy[i] = 0.98  # the BIGGEST drop at bar 64 -> 128.0s
    a1 = make_analysis(bpm=120.0, n_bars=96, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    # PARKED: even with a real biggest drop present, the plan never flags a chop.
    assert not any(getattr(p, "chop", False) for p in plan.placements)

    # Dormant-but-intact: calling the helper directly still flags exactly the loudest produced drop.
    produced = [p for p in plan.placements if getattr(p, "build_bars", 0) > 0]
    assert produced, "test needs at least one produced drop to exercise the parked helper"
    planner._flag_chop_on_biggest_drop(plan.placements, a1)
    chopped = [p for p in plan.placements if getattr(p, "chop", False)]
    assert len(chopped) == 1, "the helper still flags exactly one drop when called"
    assert chopped[0].build_bars > 0  # it's a produced drop

    def energy_at(anchor):
        i = min(range(len(a1.downbeats)), key=lambda k: abs(a1.downbeats[k] - anchor))
        return a1.energy_curve[i]
    assert energy_at(chopped[0].anchor) == max(energy_at(p.anchor) for p in produced)


def test_no_chop_when_no_produced_drop(monkeypatch):
    """A flat song with no real drop -> no produced drop -> no chop (nothing to showcase)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=[0.5] * 64)  # no low->high transition -> no drops
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    assert not any(getattr(p, "chop", False) for p in plan.placements)


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


def test_safe_build_bars_shrinks_across_a_natural_breakdown():
    """BUG REPRODUCTION (founder ear-test): Father Ocean x Der Lagi's real drop 2 has a natural
    breakdown (measured source energy ~0.047-0.049) in the MIDDLE of what would be a 3-bar build
    window. The pre-existing build (filter+volume climb, unrelated to Step 3) applied blindly there
    tipped an already-near-silent bar into a full second of TRUE silence — 'a continuous song can't
    go blank'. The build must shrink to only the bars that actually have something to build from."""
    downbeats = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]  # bar indices 0..5; anchor at 10.0 (index 5)
    energy = [0.5, 0.5, 0.05, 0.05, 0.5, 0.9]  # bars@4.0 and @6.0 are a real breakdown
    assert planner._safe_build_bars(downbeats, energy, anchor=10.0, max_bars=3) == 1  # only bar@8.0 counts


def test_safe_build_bars_zero_when_bar_right_before_anchor_is_quiet():
    downbeats = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    energy = [0.5, 0.5, 0.5, 0.5, 0.05, 0.9]  # the bar RIGHT before the anchor is the quiet one
    assert planner._safe_build_bars(downbeats, energy, anchor=10.0, max_bars=3) == 0  # no safe runway


def test_safe_build_bars_unchanged_when_all_healthy():
    downbeats = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    energy = [0.5, 0.5, 0.5, 0.5, 0.5, 0.9]
    assert planner._safe_build_bars(downbeats, energy, anchor=10.0, max_bars=3) == 3  # nothing to shrink


def test_safe_build_bars_defaults_to_max_without_data():
    assert planner._safe_build_bars([], [], anchor=10.0, max_bars=3) == 3  # can't judge -> unchanged


def test_produce_drops_shrinks_build_across_a_source_breakdown():
    """Integration: `_produce_drops` must shrink a produced drop's build rather than let it cross a
    genuine breakdown in Song 1's own source (reproduces the real founder ear-test bug)."""
    from app.models import Placement
    a1 = make_analysis(bpm=120.0, n_bars=48)  # downbeats every 2.0s -> bar index 40 = 80.0s
    a1.energy_curve = [0.3] * 48
    a1.energy_curve[36] = a1.energy_curve[37] = 0.05  # a real breakdown right before the drop
    a1.energy_curve[38] = a1.energy_curve[39] = 0.5    # healthy in the 2 bars right before the anchor
    a1.energy_curve[40] = 0.95
    placements = [Placement(anchor=80.0, vocal_src=(0.0, 8.0))]
    out = planner._produce_drops(placements, [80.0], [], 1.0, 120.0, a1)
    assert 0 < out[0].build_bars < planner._BUILD_BARS  # shrunk (2), not the full 3, not zero


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


def test_throws_echo_on_every_safe_drop(monkeypatch):
    """Step 2: the vocal rings out with an echo throw on EVERY big drop (not just the climax) —
    wherever the echo tail is clear of the next lead vocal."""
    from app.models import Placement
    placements = [Placement(anchor=10.0, vocal_src=(0.0, 8.0)),
                  Placement(anchor=100.0, vocal_src=(0.0, 8.0)),
                  Placement(anchor=200.0, vocal_src=(0.0, 8.0))]  # far apart, tails clear
    out = planner._produce_drops(placements, [10.0, 100.0, 200.0], [], 1.0, 120.0)
    assert sum(1 for p in out if p.echo) >= 2  # more than just the climax throws now


def test_throw_skipped_when_next_drop_is_within_the_echo_tail(monkeypatch):
    """R1 safety generalised: don't throw an echo whose tail would ring over the NEXT vocal."""
    from app.models import Placement
    p = [Placement(anchor=10.0, vocal_src=(0.0, 8.0)),   # dry end 18
         Placement(anchor=19.0, vocal_src=(0.0, 8.0))]   # next entry 19 — inside the echo tail
    out = planner._produce_drops(p, [10.0, 19.0], [], 1.0, 120.0)
    assert out[0].echo is False   # its echo tail would ring over the next drop's vocal -> suppressed
    assert out[1].echo is True    # the last one is clear


def test_extract_json_tolerates_prose():
    assert llm.extract_json('sure!\n{"placements": []}\nthanks') == {"placements": []}


def test_produced_drop_gets_a_bass_pull(monkeypatch):
    """Step 3: on a confident pair, a produced drop (build) also gets the tension arc — a `bass`
    StemMove that RAMPS DOWN (a genuine decline, not a flat hold) across the cut+build, slamming back
    at the anchor, and (with runway) an `other` StemMove ramping the melody down for the stretch
    before the build. Founder correction: a continuous element must LOWER, never CUT — both moves
    start at gain_from=1.0 so the decline is audible, not reached via an instant declick."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95  # a big drop at bar 40 -> 80.0s
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    drop_moves = [m for m in plan.stem_moves if m.gain_to == 0.0]  # the drop tension-arc moves only
    assert drop_moves, "a produced drop should carry the tension-arc stem moves"
    assert all(m.gain_from == 1.0 for m in drop_moves)  # a real decline
    assert all(m.stem in ("bass", "other") for m in drop_moves)  # the drop arc rides bass + melody
    produced = [p.anchor for p in plan.placements if getattr(p, "build_bars", 0) > 0]
    # the bass move slams back on a produced placement's anchor (end == that anchor)
    for m in drop_moves:
        if m.stem == "bass":
            assert m.end in produced and m.start < m.end
        else:  # "other" cuts end BEFORE the anchor (where the build begins), not at it
            assert m.end not in produced and m.start < m.end


def test_beat_up_move_wired_into_the_plan(monkeypatch):
    """Wave 2's 2nd move: build_mix_plan attaches a beat-up (melody duck) move on a confident, energetic
    pair, and it never overlaps any of the drop tension-arc moves already in the same plan."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.6] * 64  # generally energetic throughout, well above the beat-up floor
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95  # a big drop at bar 40 -> 80.0s
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    beat_ups = [m for m in plan.stem_moves if m.gain_to == fence._BEAT_UP_TARGET]
    assert beat_ups, "an energetic beat-only stretch should get a beat-up move"
    bu = beat_ups[0]
    assert bu.stem == "other" and bu.gain_from == 1.0
    for m in plan.stem_moves:
        if m is bu:
            continue
        assert not (bu.start < m.end and bu.end > m.start), "beat-up overlaps another stem move"


def test_breakdown_move_wired_into_the_plan(monkeypatch):
    """Wave 2's 3rd move: build_mix_plan attaches a breakdown (drums+bass fade to a simmer) on a
    confident, energetic pair — on a DIFFERENT clear stretch than the beat-up, never overlapping any
    other stem move that shares a stem (drums/bass), and 'other' left untouched (never all-muted)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.6] * 96  # long, energetic song with room for both beat-up and breakdown
    for i in range(52, 56):
        energy[i] = 0.2
    for i in range(56, 64):
        energy[i] = 0.95  # a big drop mid-song
    a1 = make_analysis(bpm=120.0, n_bars=96, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    bd = [m for m in plan.stem_moves if m.gain_to == fence._BREAKDOWN_FLOOR]
    assert bd, "an energetic beat-only stretch should get a breakdown move"
    assert {m.stem for m in bd} == {"drums", "bass"} and all(m.gain_from == 1.0 for m in bd)
    # no two moves that share a stem may overlap in time (the referee's own rule, checked at plan level)
    from collections import defaultdict
    by_stem = defaultdict(list)
    for m in plan.stem_moves:
        by_stem[m.stem].append((m.start, m.end))
    for spans in by_stem.values():
        spans.sort()
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            assert e1 <= s2 + 1e-9, "two same-stem moves overlap"
    # the whole plan still passes the real referee (never-all-muted, on-beat, etc.)
    validate.assert_plan(plan, a1, a2)


def test_stem_moves_never_overlap_song1s_own_vocal(monkeypatch):
    """BUG REPRODUCTION (founder ear-test): a hollowed-out backing (no bass, no melody) under Father
    Ocean's OWN vocal leading into a drop read as the mix being broken, not stripped-back. Build a
    real plan where his vocal leads right into a produced drop and assert no stem move ever overlaps
    any of his own vocal regions."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95  # a big drop at bar 40 -> 80.0s
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy, vocal_regions=[(74.0, 80.0)])  # FO sings into the drop
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    assert plan.s1_vocal_regions, "the setup should give Father Ocean a predrop lick into the drop"
    for m in plan.stem_moves:
        for s, e in plan.s1_vocal_regions:
            assert not (s < m.end and e > m.start), f"{m.stem} [{m.start},{m.end}] overlaps s1 vocal [{s},{e}]"


def test_shaky_song_has_no_stem_moves(monkeypatch):
    """A shaky grid plays a plain, safe beat — no auto-performed stem moves (same gate as build/echo)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(40, 48):
        energy[i] = 0.95
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a1.bpm_confidence = 0.3  # shaky -> no fancy moves
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.stem_moves == []


def test_stem_move_window_matches_the_build(monkeypatch):
    """The bass move's window covers the build into the drop (it steps back the placement's actual
    build_bars along the real grid) PLUS the cut stretch before it (fence._CUT_BARS more bars back),
    so the bass ramps down through the whole tension arc, and the melody's cut ends a full
    fence._CUT_RECOVERY_BARS before the build begins (giving it time to recover before the build's
    own quiet opening bar takes over — avoids the two quiet moments stacking)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (40.0, 56.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)

    for p in plan.placements:
        build_bars = getattr(p, "build_bars", 0)
        if build_bars <= 0:
            continue
        anchor_i = min(range(len(a1.downbeats)), key=lambda k: abs(a1.downbeats[k] - p.anchor))
        build_start = a1.downbeats[max(0, anchor_i - build_bars)]
        other_end = a1.downbeats[max(0, anchor_i - build_bars - fence._CUT_RECOVERY_BARS)]
        cut_start = a1.downbeats[max(0, anchor_i - build_bars - fence._CUT_RECOVERY_BARS - fence._CUT_BARS)]
        bass = next((m for m in plan.stem_moves if m.stem == "bass" and m.end == p.anchor), None)
        other = next((m for m in plan.stem_moves if m.stem == "other" and m.end == other_end), None)
        assert bass is not None and bass.start == cut_start  # bass ramps down from the cut start onward
        if cut_start < other_end:
            assert other is not None and other.start == cut_start
            assert other_end < build_start or fence._CUT_RECOVERY_BARS == 0  # melody recovers before the build


def test_vocal_anchors_land_on_8bar_phrase_lines(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # force rules path
    energy = [0.3] * 96
    for i in range(26, 34):
        energy[i] = 0.95   # a drop starting on a non-phrase bar (26)
    for i in range(66, 74):
        energy[i] = 0.98
    a1 = make_analysis(bpm=120.0, n_bars=96, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (40.0, 70.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    phrase = a1.downbeats[::8]
    assert plan.placements
    assert all(any(abs(p.anchor - ps) <= 0.06 for ps in phrase) for p in plan.placements)
