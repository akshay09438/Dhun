"""Tests for the arrangement data models — additive changes that must not break
M3-era single-placement plans cached on disk.
"""

from app.models import (CamelotFit, MixPlan, Placement, StemMove, VocalChainConfig,
                        chain_config_hash)


def test_placement_and_arrangement_roundtrip():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        take=2,
        placements=[
            Placement(anchor=16.0, vocal_src=(16.0, 32.0)),
            Placement(anchor=64.0, vocal_src=(40.0, 56.0), beat_breath=True),
        ],
    )
    reloaded = MixPlan.model_validate_json(plan.model_dump_json())
    assert reloaded.placements[1].beat_breath is True
    assert reloaded.take == 2


def test_old_single_placement_json_still_parses():
    # an M3-era plan with no placements/take must still load (additive change)
    m3 = (
        '{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
        '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}'
    )
    plan = MixPlan.model_validate_json(m3)
    assert plan.placements == [] and plan.take == 1
    assert plan.s1_vocal_regions == []  # Slice B fields default empty on old plans


def test_bed_stretch_is_additive_and_defaults_to_one():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=128.16, vocal_stretch=0.89, vocal_src=(16.0, 40.0), anchor=16.0,
        bed_stretch=1.05,
    )
    assert MixPlan.model_validate_json(plan.model_dump_json()).bed_stretch == 1.05
    # an old plan with no bed_stretch still parses -> defaults to 1.0
    old = ('{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
           '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}')
    assert MixPlan.model_validate_json(old).bed_stretch == 1.0


def test_slice_b_contrast_and_fx_roundtrip():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        placements=[Placement(anchor=16.0, vocal_src=(0.0, 12.0), fx="sweep_in")],
        s1_vocal_regions=[(40.0, 52.0)],
    )
    reloaded = MixPlan.model_validate_json(plan.model_dump_json())
    assert reloaded.placements[0].fx == "sweep_in"
    assert reloaded.s1_vocal_regions == [(40.0, 52.0)]


def test_stem_move_roundtrip_and_defaults():
    # Step 3: a StemMove has sensible pull defaults (full -> silent) and survives a round-trip
    mv = StemMove(stem="bass", start=64.0, end=70.0)
    assert mv.gain_from == 1.0 and mv.gain_to == 0.0  # the bass-pull default
    reloaded = StemMove.model_validate_json(mv.model_dump_json())
    assert (reloaded.stem, reloaded.start, reloaded.end) == ("bass", 64.0, 70.0)


def test_stem_moves_are_additive_and_default_empty():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        stem_moves=[StemMove(stem="bass", start=10.0, end=16.0, gain_from=1.0, gain_to=0.0)],
    )
    reloaded = MixPlan.model_validate_json(plan.model_dump_json())
    assert reloaded.stem_moves[0].stem == "bass" and reloaded.stem_moves[0].gain_to == 0.0
    # an old plan with no stem_moves still parses -> defaults to [] (today's flat bed)
    old = ('{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
           '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}')
    assert MixPlan.model_validate_json(old).stem_moves == []


def test_mixplan_window_defaults_none_and_roundtrips():
    base = dict(mix_id="m", song1_id="a", song2_id="b", master_bpm=122.0,
                vocal_stretch=1.0, vocal_src=(0.0, 8.0), anchor=4.0)
    assert MixPlan(**base).window is None                      # additive default
    p = MixPlan(**base, window=(30.0, 120.0))
    assert p.window == (30.0, 120.0)
    assert MixPlan.model_validate(p.model_dump()).window == (30.0, 120.0)  # JSON round-trip


# ---------------------------------------------------------------- Phase 0 (Slice 1 / 2a scaffolding)


def test_vocal_chain_config_ships_off_with_bounded_defaults():
    cfg = VocalChainConfig()
    assert cfg.enabled is False                       # ships off
    assert cfg.saturate_wet == 0.25                   # under the 0.5 hard cap
    assert cfg.presence_gain_db == 2.5                # under the 6.0 hard cap
    assert cfg.pitch_max_semitones == 3.0 and cfg.pitch_engine == "rubberband"


def test_chain_config_hash_is_stable_and_dial_sensitive():
    assert chain_config_hash(VocalChainConfig()) == chain_config_hash(VocalChainConfig())  # stable
    # any dial change yields a different hash -> a fresh render (no stale cache during tuning)
    assert chain_config_hash(VocalChainConfig(saturate_wet=0.30)) != chain_config_hash(VocalChainConfig())
    assert chain_config_hash(VocalChainConfig(enabled=True)) != chain_config_hash(VocalChainConfig())


def test_camelot_fit_and_chain_hash_are_additive_on_the_plan():
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        camelot_fit=CamelotFit(song1_camelot="8A", song2_camelot="9A", compatible=True),
        chain_config_hash="deadbeef",
    )
    r = MixPlan.model_validate_json(plan.model_dump_json())
    assert r.camelot_fit.compatible is True and r.camelot_fit.song2_camelot == "9A"
    assert r.chain_config_hash == "deadbeef"
    # an old plan with neither field still parses -> None / "" defaults
    old = ('{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
           '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}')
    assert MixPlan.model_validate_json(old).camelot_fit is None
    assert MixPlan.model_validate_json(old).chain_config_hash == ""


def test_vocal_process_move_dials_default_to_a_noop():
    from app.models import VocalProcessMove
    m = VocalProcessMove(placement_id="p", start_bar=0, end_bar=4)
    assert m.pitch_semitones == 0.0 and m.saturate_wet == 0.0 and m.reverb_wet == 0.0


def test_vocal_and_duck_moves_roundtrip_and_are_additive_on_the_plan():
    from app.models import DuckMove, VocalProcessMove
    plan = MixPlan(
        mix_id="m" * 64, song1_id="a" * 64, song2_id="b" * 64,
        master_bpm=120.0, vocal_stretch=1.0, vocal_src=(16.0, 40.0), anchor=16.0,
        vocal_moves=[VocalProcessMove(placement_id="p0", start_bar=8, end_bar=24,
                                      pitch_semitones=-1.0, saturate_wet=0.3,
                                      reason="key_correction: 1A->6A")],
        duck_moves=[DuckMove(key_placement_id="p0", depth_db=1.5, attack_ms=5, release_ms=120)],
    )
    r = MixPlan.model_validate_json(plan.model_dump_json())
    assert r.vocal_moves[0].pitch_semitones == -1.0 and r.vocal_moves[0].saturate_wet == 0.3
    assert r.duck_moves[0].target_stems == ["drums", "bass", "other"]
    # an old plan with neither field still parses -> [] (chain off, today's plain vocal)
    old = ('{"mix_id":"m","song1_id":"a","song2_id":"b","master_bpm":120.0,'
           '"vocal_stretch":1.0,"vocal_src":[16.0,40.0],"anchor":16.0}')
    assert MixPlan.model_validate_json(old).vocal_moves == []
    assert MixPlan.model_validate_json(old).duck_moves == []
