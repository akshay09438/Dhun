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
    monkeypatch.setattr(planner, "USE_AI_ARRANGEMENT", True)  # Phase 0 T1: AI path is opt-in now
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


def test_ai_arrangement_is_off_by_default(monkeypatch):
    """Phase 0 T1: the disliked AI arranger no longer activates on API-key presence. By default
    the mix uses the loved rules path and _ai_arrange is not even called — even when it WOULD
    return a valid AI arrangement."""
    from app.models import Placement
    called: list[int] = []
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: (
        called.append(1) or [Placement(anchor=16.0, vocal_src=(16.0, 24.0))]))
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    mix = planner.build_mix_plan("m" * 64, a1, a2, prompt="build it up")

    assert planner.USE_AI_ARRANGEMENT is False  # ships off
    assert mix.source == "rules"                # the loved arrangement
    assert called == []                         # the AI path was never invoked


def test_camelot_fit_is_attached_and_compatible(monkeypatch):
    """Phase 0 T1.2: every plan carries the informational key-fit. Same key (8A/8A) -> compatible."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, key="8A")
    a2 = make_analysis(bpm=118.0, key="8A", vocal_regions=[(16.0, 40.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.camelot_fit is not None
    assert plan.camelot_fit.compatible is True
    assert plan.camelot_fit.song1_camelot == "8A" and plan.camelot_fit.song2_camelot == "8A"


def test_camelot_fit_flags_a_clash_but_does_not_gate(monkeypatch):
    """Phase 0 T1.2: a clashing key is OBSERVED (compatible=False) but never gates — the mix
    still builds. This slice is read-only observation, not a new decline reason (that's Slice 2d)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, key="8A")
    a2 = make_analysis(bpm=118.0, key="3B", vocal_regions=[(16.0, 40.0)])  # a clashing key

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.camelot_fit.compatible is False  # flagged...
    assert plan.placements                       # ...but not declined — the mix builds anyway


def test_plan_emits_no_vocal_moves_while_the_chain_is_disabled(monkeypatch):
    """Phase 0 Slice 2a: the vocal-chain ships OFF, so the plan emits no timeline processing
    instructions — the render stays today's plain vocal (byte-identical), exactly like an empty
    stem_moves. The instruction machinery exists; it just isn't fired yet."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.vocal_moves == [] and plan.duck_moves == []


def test_enabled_chain_emits_one_move_per_placement(monkeypatch):
    """Phase 0 Slice 2b: with the chain enabled, the planner emits one VocalProcessMove (with the
    config's dials) and one keyed DuckMove per placement — and the plan still passes the referee."""
    from app.models import VocalChainConfig
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2, chain=VocalChainConfig(enabled=True))

    assert plan.vocal_moves and len(plan.vocal_moves) == len(plan.placements)
    assert len(plan.duck_moves) == len(plan.placements)
    vm = plan.vocal_moves[0]
    assert vm.saturate_wet == 0.25 and vm.presence_gain_db == 2.5 and vm.highpass_hz == 90
    assert vm.pitch_semitones == 0.0  # key-correction repair is Slice 2d (still off)
    assert plan.duck_moves[0].key_placement_id == plan.vocal_moves[0].placement_id
    validate.assert_plan(plan, a1, a2)  # the enabled plan is clean under the referee (P1-P5)


def test_a_disabled_stage_emits_its_neutral_dial(monkeypatch):
    """Each of the nine stages is independently disable-able: a stage turned off in the config emits
    its NEUTRAL dial (the renderer treats a neutral dial as off), while enabled stages keep theirs."""
    from app.models import VocalChainConfig
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    cfg = VocalChainConfig(enabled=True, saturate_enabled=False, presence_enabled=False, duck_enabled=False)

    plan = planner.build_mix_plan("m" * 64, a1, a2, chain=cfg)

    vm = plan.vocal_moves[0]
    assert vm.saturate_wet == 0.0 and vm.presence_gain_db == 0.0  # off stages -> neutral dials
    assert vm.highpass_hz == 90 and vm.compress_ratio == 3.0      # on stages keep their dials
    assert plan.duck_moves == []                                  # duck disabled -> no DuckMove


def test_pitch_repair_off_by_default_leaves_pitch_zero(monkeypatch):
    """Slice 2d gate defaults OFF: even a clashing pair that COULD be shifted emits pitch_semitones 0
    unless pitch_repair_enabled is set — so nothing pitch-corrects in the shipped app."""
    from app.models import VocalChainConfig
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, key="8A")
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)], key="5A")  # clash, fixable by -1
    plan = planner.build_mix_plan("m" * 64, a1, a2, chain=VocalChainConfig(enabled=True))
    assert plan.vocal_moves and all(vm.pitch_semitones == 0.0 for vm in plan.vocal_moves)


def test_pitch_repair_on_emits_the_camelot_shift(monkeypatch):
    """With pitch_repair_enabled, the planner emits the shortest key-correction shift on every move,
    and the plan still passes the referee (P1: within ±3)."""
    from app.models import VocalChainConfig
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, key="8A")
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)], key="5A")
    plan = planner.build_mix_plan("m" * 64, a1, a2,
                                  chain=VocalChainConfig(enabled=True, pitch_repair_enabled=True))
    assert plan.vocal_moves and all(vm.pitch_semitones == -1.0 for vm in plan.vocal_moves)
    validate.assert_plan(plan, a1, a2)  # within ±3 -> referee clean


def test_pitch_repair_declines_a_pair_beyond_the_safe_band(monkeypatch):
    """A clash whose nearest fix exceeds the ±cap band DECLINES — never warped past the safe band."""
    import pytest
    from app.models import VocalChainConfig
    from app.planner.plan import MixDeclined
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, key="10B")
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)], key="11A")  # 10B/11A -> >±3
    with pytest.raises(MixDeclined):
        planner.build_mix_plan("m" * 64, a1, a2,
                               chain=VocalChainConfig(enabled=True, pitch_repair_enabled=True))


def test_plan_carries_the_chain_config_hash(monkeypatch):
    """Phase 0 T1.4: the plan records the (default, off) vocal-chain config hash for reproducibility."""
    from app.models import VocalChainConfig, chain_config_hash
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.chain_config_hash == chain_config_hash(VocalChainConfig())


def test_contrast_and_sweep_on_a_confident_pair(monkeypatch):
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(60.0, 90.0)])  # S1 sings in a gap
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (30.0, 50.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.s1_vocal_regions  # Song 1's own vocal answers in a gap
    assert sum(1 for p in plan.placements if p.fx == "sweep_in") == 1  # one subtle sweep


def test_instrumental_only_beat_places_no_song1_vocal(monkeypatch):
    """A beat that is really a vocal song (e.g. Merrygo = a D&B remix of Khuda Jaane) must contribute
    its MUSIC ONLY: the planner must never weave in Song 1's own vocal, or it overlaps Song 2's lyrics.
    Same confident pair as the contrast test, but with the beat marked instrumental-only."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    monkeypatch.setattr(planner.instrumental_beats, "is_instrumental_only", lambda sid: True)
    a1 = make_analysis(bpm=120.0, n_bars=64, vocal_regions=[(60.0, 90.0)])  # S1 sings, but is instrumental-only
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (30.0, 50.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.s1_vocal_regions == []  # zero seconds of Song 1's own vocal placed
    assert sum(1 for p in plan.placements if p.fx == "sweep_in") == 1  # Song 2's flourish still fires


def test_merrygo_beat_is_marked_instrumental_only():
    from app.planner import instrumental_beats
    assert instrumental_beats.is_instrumental_only(
        "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480")


def test_hand_marked_main_drop_anchors_the_hook(monkeypatch):
    """A beat whose energy is too flat to auto-detect a drop can have its main drop marked by ear;
    the vocal's hook must then land ON that marked drop, not spread blindly across the song."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    # A beat with a FLAT energy curve (no auto-detectable drop), marked at 40s.
    a1 = make_analysis(bpm=85.0, n_bars=48, energy=None)  # energy=None -> flat 0.5 everywhere
    a2 = make_analysis(bpm=90.0, vocal_regions=[(8.0, 30.0), (40.0, 70.0)])
    from app.planner import main_drops as main_drops_mod
    monkeypatch.setattr(planner.fence, "energy_drops", lambda *a, **k: [])  # force "no auto drop"
    monkeypatch.setattr(planner.hooks, "hook_for", lambda sid: (8.0, 24.0))  # Song 2 has a signature hook
    monkeypatch.setattr(main_drops_mod, "main_drops_for",
                        lambda sid: [40.0] if sid == a1.song_id else [])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    # some placement anchors on (near) the marked 40s downbeat...
    assert any(abs(p.anchor - 40.0) <= 1.5 for p in plan.placements), \
        f"no placement near the marked 40s drop: {[round(p.anchor, 1) for p in plan.placements]}"
    # ...and it's the one carrying the HOOK region (~8s), not the setup region (~40s): the signature
    # line lands on the drop. (Exact slice bounds shift under warp/snap, so assert the region, not ==.)
    on_drop = min(plan.placements, key=lambda p: abs(p.anchor - 40.0))
    assert on_drop.vocal_src[0] < 30.0, f"the setup region, not the hook, landed on the drop: {on_drop.vocal_src}"


def test_merrygo_beat_has_a_hand_marked_main_drop():
    from app.planner import main_drops
    assert main_drops.main_drops_for(
        "4fc82b59807fcbd3071bca7f612e2311f044f0e203f8e82895d7682d67629480") == [40.0]


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


def test_section_labels_do_not_affect_a_populated_regions_plan(monkeypatch):
    """B.2 evidence (2026-07-10): with vocal_regions populated (every catalog song), the RULES plan is
    IDENTICAL whether the analysis carries accurate section labels, garbage labels, or none — proving
    the ~23%-precise section map is out of the drop / hook / vocal-slice decision path."""
    from app.models import Section
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(40, 48):
        energy[i] = 0.95  # a real energy drop the plan should find (from ENERGY, not a label)
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (24.0, 44.0)])
    base = planner.build_mix_plan("x" * 64, a1, a2, take=1)
    # the SAME pair, but both songs carry GARBAGE section labels spanning the whole track
    a1g = a1.model_copy(update={"sections": [Section(start=0.0, end=999.0, label="chorus")]})
    a2g = a2.model_copy(update={"sections": [Section(start=0.0, end=999.0, label="drop")]})
    garbled = planner.build_mix_plan("x" * 64, a1g, a2g, take=1)
    assert [(p.anchor, p.vocal_src) for p in base.placements] == \
           [(p.anchor, p.vocal_src) for p in garbled.placements]
    assert base.stem_moves == garbled.stem_moves and base.s1_vocal_regions == garbled.s1_vocal_regions


# Deliberately RE-baselined 2026-07-10 (Task 1 — loudest-slice hook guess removed): eyeballed the new
# no-hook plan — vocals now lay in the song's own time order (anchor 0.0→region 0-16, anchor 32→region
# 24-44, the drop wraps to region 1), no longer loudness-selecting which region lands on the drop; the
# drop keeps its energy-driven produced build. Still comes from ENERGY + vocal_regions, not section
# labels (see test_section_labels_do_not_affect_a_populated_regions_plan). Re-baseline ONLY after
# diffing + eyeballing.
_GATE_B_PLAN_SIG = "e57725c75d3314ae"


def test_gate_b_plan_determinism_on_a_fixed_analysis(monkeypatch):
    """GATE B — plan determinism GIVEN A FIXED ANALYSIS (complements Gate A = render determinism, in
    test_render.py). A planner or analyzer change is SUPPOSED to break this: re-baseline DELIBERATELY
    — diff the old plan against the new, eyeball that the drops sit where the energy actually jumps —
    never blind-update the signature."""
    import hashlib
    import json
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 48
    for i in range(36, 40):
        energy[i] = 0.2
    for i in range(40, 48):
        energy[i] = 0.95
    a1 = make_analysis(bpm=120.0, n_bars=48, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 16.0), (24.0, 44.0)])
    plan = planner.build_mix_plan("g" * 64, a1, a2, take=1)
    sig = hashlib.sha256(json.dumps({
        "placements": [(round(p.anchor, 3), list(p.vocal_src), p.beat_breath, getattr(p, "build_bars", 0))
                       for p in plan.placements],
        "stem_moves": [(m.stem, round(m.start, 3), round(m.end, 3), m.gain_from, m.gain_to)
                       for m in plan.stem_moves],
        "s1_vocal_regions": [list(r) for r in plan.s1_vocal_regions], "source": plan.source,
    }).encode()).hexdigest()[:16]
    assert sig == _GATE_B_PLAN_SIG, f"plan changed vs the pinned baseline — RE-BASELINE DELIBERATELY: {sig}"


def test_declines_when_unmixable():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=158.0, vocal_regions=[(16.0, 40.0)])  # still too far even at ±15%
    with pytest.raises(planner.MixDeclined) as exc:
        planner.build_mix_plan("m" * 64, a1, a2)
    assert "tempo" in str(exc.value).lower()


def test_long_song_vocal_spans_the_full_song(monkeypatch):
    """The anti-clustering guarantee, on the FULL song. The good-parts window is disabled (founder
    decision 2026-07-09: remix the whole song, not the best ~90s), so a long song is NOT cropped —
    plan.window is None — and the vocal must reach both the first third AND the final third across the
    whole track, never clustered in one loud spot."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)  # deterministic
    energy = [0.3] * 128
    for i in range(56, 72):  # a real mid-song drop
        energy[i] = 0.9
    a1 = make_analysis(bpm=120.0, n_bars=128, energy=energy)  # ~256s (~4.3 min)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 30.0), (40.0, 70.0)])

    plan = planner.build_mix_plan("m" * 64, a1, a2)

    assert plan.window is None                  # full song, no ~90s crop
    anchors = sorted(p.anchor for p in plan.placements)  # absolute times across the whole track
    assert anchors[0] <= 90.0                   # a vocal enters in the first third (no long empty intro)
    assert anchors[-1] >= 150.0                 # ...and one reaches the final third of the ~256s song
    assert anchors[-1] - anchors[0] >= 80.0     # spanning a real stretch, not clustered


def test_hook_lands_on_the_loudest_drop():
    """The signature HOOK must land on the LOUDEST drop (the MAIN drop the window is built around),
    not merely the first drop in time. Founder ear-test 2026-07-09: 'aankhein teri kitni haseen' has
    to hit the big beat drop. Tested directly on the arranger with two drops of different energy."""
    from app.models import Section, TrackAnalysis

    downs = [round(2.0 * i, 3) for i in range(61)]   # a downbeat every 2s, 0..120s
    energy = [0.3] * 61
    energy[25] = 0.6                                  # a MODERATE drop at ~50s
    energy[45] = 0.95                                 # the LOUDEST drop at ~90s
    a1g = TrackAnalysis(song_id="beat", status="ready", bpm=120.0,
                        beats=[round(1.0 * i, 3) for i in range(121)], downbeats=downs,
                        phrase_starts=downs[::8], energy_curve=energy,
                        sections=[Section(start=0.0, end=120.0, label="verse")])
    opts = {
        "anchors_ranked": [10.0, 50.0, 90.0], "drops": [50.0, 90.0],
        "vocal_slices": [(0.0, 20.0), (40.0, 60.0)], "vocal_peaks": [(0.0, 20.0), (40.0, 60.0)],
        "vocal_stretch": 1.0, "hook": (10.0, 30.0), "track_end": 120.0,
        "a1_grid": a1g, "master_bpm": 120.0,
    }

    placements = planner._default_arrangement(opts, take=1)

    hookp = [p for p in placements if abs(p.vocal_src[0] - 10.0) < 0.6]  # the entry carrying the hook slice
    assert hookp, "the hook slice was not placed"
    assert hookp[0].anchor == 90.0                                       # the loudest drop, not the 50s one


def test_clustered_ai_arrangement_is_spread_by_the_guard(monkeypatch):
    """Even if the AI clusters every vocal in the middle, the arc guard rebuilds a spread
    arrangement so the song never has an empty half."""
    monkeypatch.setattr(planner, "USE_AI_ARRANGEMENT", True)  # Phase 0 T1: AI path is opt-in now
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
    monkeypatch.setattr(planner, "USE_AI_ARRANGEMENT", True)  # Phase 0 T1: AI path is opt-in now
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


def test_no_hook_lays_vocals_in_song_order_not_loudest():
    """Task 1 (2026-07-10): with NO hand-marked hook, the arranger must not GUESS which slice is the
    memorable hook by landing Song 2's LOUDEST region on the drop (that guess measured ~28s off as a
    hook detector). It lays the vocal regions across the anchors in the song's own time order — the
    earliest entry carries the earliest region — so no slice is privileged onto the drop."""
    from app.models import Section, TrackAnalysis

    downs = [round(2.0 * i, 3) for i in range(61)]     # a downbeat every 2s, 0..120s
    energy = [0.3] * 61
    energy[45] = 0.95                                  # the LOUDEST drop at ~90s (final third)
    a1g = TrackAnalysis(song_id="beat", status="ready", bpm=120.0,
                        beats=[round(1.0 * i, 3) for i in range(121)], downbeats=downs,
                        phrase_starts=downs[::8], energy_curve=energy,
                        sections=[Section(start=0.0, end=120.0, label="verse")])
    # An EARLY region and a LATE region; the LATE one is the loudest (vocal_peaks lists it first).
    # NO "hook" key -> the no-guess path. Old code would land the loud late region on the 90s drop.
    opts = {
        "anchors_ranked": [10.0, 50.0, 90.0], "drops": [90.0],
        "vocal_slices": [(4.0, 24.0), (60.0, 80.0)],
        "vocal_peaks": [(60.0, 80.0), (4.0, 24.0)],    # loudest-first (late region loudest)
        "vocal_stretch": 1.0, "track_end": 120.0,
        "a1_grid": a1g, "master_bpm": 120.0,
    }  # note: NO "hook"

    placements = planner._default_arrangement(opts, take=1)

    ordered = sorted(placements, key=lambda p: p.anchor)
    assert ordered[0].vocal_src[0] == 4.0              # earliest entry carries the earliest region
    drop = [p for p in placements if p.anchor == 90.0]
    assert drop and drop[0].vocal_src[0] != 60.0       # the loudest region is NOT forced onto the drop


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
    monkeypatch.setattr(planner, "USE_AI_ARRANGEMENT", True)  # Phase 0 T1: AI path is opt-in now
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


def test_hook_lands_on_the_drop(monkeypatch):
    """A curated song's signature HOOK slice is placed on the drop (the strongest anchor), not the
    loudest blob. The other entries get the setup (other vocal parts)."""
    from app.planner import hooks
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    energy = [0.3] * 64
    for i in range(20, 28):
        energy[i] = 0.95  # a clear drop at bar 20 -> 40.0s
    a1 = make_analysis(bpm=120.0, n_bars=64, energy=energy)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (30.0, 60.0)])
    monkeypatch.setattr(hooks, "hook_for", lambda sid: (30.0, 45.0))  # the marked hook slice
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    drops = fence.energy_drops(a1.energy_curve, a1.downbeats)
    on_drop = [p for p in plan.placements if any(abs(p.anchor - d) <= 0.06 for d in drops)]
    assert on_drop, "expected a placement on the drop"
    assert any(abs(p.vocal_src[0] - 30.0) <= 0.06 for p in on_drop), \
        f"hook not on the drop: {[p.vocal_src for p in on_drop]}"


def test_no_hook_falls_back_to_loudest(monkeypatch):
    """A song with no hook marker keeps the old loudest-peak behaviour (additive change)."""
    from app.planner import hooks
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    monkeypatch.setattr(hooks, "hook_for", lambda sid: None)
    a1 = make_analysis(bpm=120.0, n_bars=32)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(0.0, 20.0), (24.0, 44.0)])
    plan = planner.build_mix_plan("m" * 64, a1, a2, take=1)
    assert plan.placements  # still produces a valid arrangement


# The five SHIPPED catalog vocal donors, keyed by content id (kept in sync with data/library/manifest.json,
# role_hint "vocals"). Founder-marked their hooks by ear (2026-07-11); this guards against a silent
# regression back to the hookless no-guess path — every catalog vocal mix depends on these landing.
_CATALOG_VOCAL_DONORS = {
    "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430": "Der Lagi Lekin",
    "c0c6ab91a06e24367e84874da81d4abc285779f50e8f1aeacf70a655cabceb0b": "Don't Start Now",
    "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20": "Tujhe Bhula Diya",
    "ae132f3a444f5121d75097a44110a0323365e6dc4a8d0736a924c00b2ac210c1": "With You",
    "6ad6903592cd668502c5f4546618aec807c6eadb974fa6437fef7180fbffddc2": "Tere Bina",
}


def test_every_catalog_vocal_donor_has_a_marked_hook():
    """Every shipped catalog vocal donor MUST carry a hand-marked hook, so the with-hook path (R1)
    runs on the real catalog instead of the hookless no-guess fallback. A donor added to the manifest
    without a hook mark should fail HERE, not ship a guessy mix."""
    from app.planner import hooks
    for sid, name in _CATALOG_VOCAL_DONORS.items():
        h = hooks.hook_for(sid)
        assert h is not None, f"{name} ({sid[:8]}) has no marked hook"
        start, end = h
        assert 0.0 <= start < end, f"{name} hook is not a valid (start<end) slice: {h}"


from app.models import TrackAnalysis


def _beat_song(track_secs=240.0):
    downs = [round(2.0 * i, 3) for i in range(int(track_secs // 2) + 1)]
    # energy low early, a clear high onset near ~200s (the main drop), so a window exists
    energy = [0.2] * len(downs)
    for i, d in enumerate(downs):
        if d >= 196.0:
            energy[i] = 0.9
    return TrackAnalysis(song_id="beat", status="ready", bpm=120.0, bpm_confidence=0.9,
                         beats=[round(1.0 * i, 3) for i in range(int(track_secs) + 1)],
                         downbeats=downs, phrase_starts=downs[::8], energy_curve=energy,
                         sections=[Section(start=0.0, end=track_secs, label="verse")],
                         vocal_regions=[])


def _vocal_song():
    return TrackAnalysis(song_id="voc", status="ready", bpm=120.0, bpm_confidence=0.9,
                         beats=[round(0.5 * i, 3) for i in range(480)],
                         downbeats=[round(2.0 * i, 3) for i in range(120)],
                         vocal_regions=[(20.0, 60.0), (120.0, 150.0)])


def test_build_mix_plan_uses_the_full_song(monkeypatch):
    """The good-parts window is disabled (founder decision 2026-07-09): even a long song is remixed
    FULL-length, never cropped to the best ~90s, so plan.window is None. The window machinery is
    proven still-working in test_validate_plan_clean_on_a_windowed_plan (which flips the flag on)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)     # force the deterministic path
    p = planner.build_mix_plan("m1", _beat_song(240.0), _vocal_song())
    assert p.window is None                                    # full song, no ~90s crop


def test_build_mix_plan_falls_back_full_track_without_a_drop(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    flat = _beat_song(240.0)
    flat = flat.model_copy(update={"energy_curve": [0.2] * len(flat.downbeats)})  # no drop
    p = planner.build_mix_plan("m2", flat, _vocal_song())
    assert p.window is None                                    # today's full-track behaviour


def test_innerbloom_is_held_out_until_its_own_verse():
    """Founder call (2026-07-16): Innerbloom plays AS ITSELF until its lyrics start at 6:17, then
    Song 2 rides in with them. Its buildup runs from ~5:45; nothing of Song 2 before the floor."""
    from app.planner import vocal_windows
    assert vocal_windows.vocal_entry_earliest_for(
        "2471e18e1eb820114c0782501babac43b6e5b52c06254da4c1fe0d9e8369c406") == 377.0


def test_unmarked_beats_have_no_vocal_entry_floor():
    """The floor is opt-in per beat: every other beat keeps today's whole-song arrangement."""
    from app.planner import vocal_windows
    assert vocal_windows.vocal_entry_earliest_for("z" * 64) == 0.0
    assert vocal_windows.vocal_entry_earliest_for("") == 0.0


def test_vocal_entry_floor_holds_song2_out_and_hands_song1_its_own_vocal(monkeypatch):
    """The two halves of the founder's rule, together: NO Song-2 vocal before the floor, and the beat
    sings its OWN vocal across the held-out head (the engine's bed excludes Song 1's vocal, so without
    this the head would play as a long instrumental instead of the record)."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    FLOOR = 120.0
    a1 = make_analysis(bpm=120.0, n_bars=200, vocal_regions=[(20.0, 60.0), (70.0, 110.0),
                                                             (130.0, 170.0)])
    a2 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 20.0), (30.0, 50.0)])
    monkeypatch.setattr(
        "app.planner.vocal_windows.vocal_entry_earliest_for",
        lambda song_id: FLOOR if song_id == a1.song_id else 0.0,
    )
    plan = planner.build_mix_plan("v" * 64, a1, a2)

    assert plan.placements, "the floor must not strand the arrangement"
    assert all(p.anchor >= FLOOR - 1e-6 for p in plan.placements), (
        f"Song 2 entered before the floor: {[p.anchor for p in plan.placements]}"
    )
    head = [r for r in (plan.s1_vocal_regions or []) if r[0] < FLOOR]
    assert head, "the beat must sing its OWN vocal across the held-out head, not play instrumental"


def test_a_floor_with_no_legal_anchor_is_ignored_not_stranded():
    """Never emit a vocal-less mix: if the floor leaves no legal anchor, drop the floor instead."""
    from app.planner import fence
    a1 = make_analysis(bpm=120.0, n_bars=16, vocal_regions=[(2.0, 8.0)])
    a2 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 10.0)])
    import app.planner.vocal_windows as vw
    real = vw.vocal_entry_earliest_for
    try:
        vw.vocal_entry_earliest_for = lambda song_id: 9_999.0  # past the end of the song
        opts = fence.arrangement_options(a1, a2)
        assert opts["vocal_entry_floor"] == 0.0, "an impossible floor must be ignored"
        assert opts["anchors_ranked"], "anchors must survive an impossible floor"
    finally:
        vw.vocal_entry_earliest_for = real


def test_held_out_window_gets_more_entries_than_a_normal_song(monkeypatch):
    """Founder call (2026-07-16): "I just want that for longer in more parts". 3 entries are sized to
    span a WHOLE song; in a held-out window they leave big instrumental holes (measured: a 94s hole in
    Innerbloom's 6:17->9:14). The count scales to the window instead — capped by how many distinct
    slices Song 2 has, so we never invent entries there is no vocal for."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    opts = {"track_end": 578.0, "vocal_slices": [(0, 40), (60, 100), (120, 160), (180, 220)]}
    assert planner._placement_count(opts, entry_floor=0.0) == planner._MAX_PLACEMENTS
    assert planner._placement_count(opts, entry_floor=377.0) == 4  # ~177s window -> 4, not 3
    # never more entries than there are distinct slices to fill them with
    assert planner._placement_count({**opts, "vocal_slices": [(0, 40)]}, entry_floor=377.0) == 3
    # and never unbounded on a very long held-out window
    assert planner._placement_count(
        {"track_end": 5000.0, "vocal_slices": [(i, i + 10) for i in range(0, 200, 20)]},
        entry_floor=10.0) == planner._MAX_HELD_OUT_PLACEMENTS


def test_held_out_setup_prefers_the_LONGEST_vocal_not_the_loudest(monkeypatch):
    """`vocal_peaks` ranks by loudness — right for spreading a few entries across a whole song, wrong
    for filling a held-out window. Measured on Wari Jawa it ranked an 8s scrap FIRST and omitted a 40s
    passage entirely. In a held-out window the setup draws longest-first so the window is real singing."""
    monkeypatch.setattr(planner, "_ai_arrange", lambda opts, prompt, take: None)
    FLOOR = 120.0
    a1 = make_analysis(bpm=120.0, n_bars=200, vocal_regions=[(20.0, 60.0)])
    a2 = make_analysis(bpm=120.0, vocal_regions=[(0.0, 8.0), (30.0, 70.0), (90.0, 130.0)])
    monkeypatch.setattr(
        "app.planner.vocal_windows.vocal_entry_earliest_for",
        lambda song_id: FLOOR if song_id == a1.song_id else 0.0,
    )
    plan = planner.build_mix_plan("w" * 64, a1, a2)
    used = [p.vocal_src for p in plan.placements]
    assert used, "the held-out window must still get vocal"
    # the 8s scrap must not crowd out the long passages
    longest = max(e - s for s, e in used)
    assert longest > 20.0, f"held-out setup picked only short scraps: {used}"
