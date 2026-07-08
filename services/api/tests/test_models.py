"""Tests for the arrangement data models — additive changes that must not break
M3-era single-placement plans cached on disk.
"""

from app.models import MixPlan, Placement, StemMove


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
