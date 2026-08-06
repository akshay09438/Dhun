"""Hermetic tests for the Rule 3 (chop & repeat) planner brain — no audio, pure scheduling."""
import numpy as np

from app.planner import rule3


def _env(sr, dur, voiced_spans):
    e = np.zeros(int(dur * sr), dtype=np.float32)
    for a, b in voiced_spans:
        e[int(a * sr):int(b * sr)] = 1.0
    return e


def test_voiced_phrases_finds_two_lines():
    sr = 100
    env = _env(sr, 40, [(10.0, 12.0), (14.0, 16.0)])
    ph = rule3.voiced_phrases(env, sr, 8.0, 20.0)
    assert len(ph) == 2
    assert abs(ph[0][0] - 10.0) < 0.2 and abs(ph[0][1] - 12.0) < 0.2


def test_word_end_extends_to_silence_then_stops():
    sr = 100
    env = _env(sr, 20, [(10.0, 12.5)])          # word ends at 12.5
    we = rule3.word_end_after(env, sr, 12.0, thr=0.5)
    assert 12.4 < we < 12.8                       # finds the word boundary, doesn't overrun


def test_pick_blocks_override_A_short_C_full():
    sr = 100
    env = _env(sr, 40, [(10.0, 12.0), (14.0, 16.0)])
    vdb = [float(x) for x in range(0, 41, 2)]     # vocal downbeats every 2s
    a_unit, c_unit = rule3.pick_blocks((10.0, 16.0), vdb, 120.0, env, sr,
                                       a_range=(10.0, 12.0), c_range=(10.0, 16.0))
    assert len(a_unit) == 1 and a_unit[0].bars == ((10.0, 12.0),)          # short tease = 1 bar
    assert rule3.unit_bars(c_unit) >= rule3.unit_bars(a_unit)               # full sentence >= tease
    assert c_unit[0].bars[0] == a_unit[0].bars[0]                           # and starts with A
    assert a_unit[0].word_end >= a_unit[0].bars[-1][1]


def test_pick_blocks_auto_A_then_B_forms_C():
    sr = 100
    env = _env(sr, 40, [(10.0, 12.0), (14.0, 16.0)])
    vdb = [float(x) for x in range(0, 41, 2)]
    a_unit, c_unit = rule3.pick_blocks((10.0, 20.0), vdb, 120.0, env, sr)
    assert len(a_unit) == 1
    assert len(c_unit) == 2                        # C = tease phrase + the next, two word-safe phrases
    assert rule3.unit_bars(c_unit) > rule3.unit_bars(a_unit)   # longer, and B never stands alone


def test_instrumental_gaps_trade_vs_whole_track():
    sr = 100
    benv = _env(sr, 40, [(20.0, 25.0)])           # the beat sings 20-25s
    gaps_keep = rule3.instrumental_gaps(benv, sr, 40.0, keep_beat_vocal=True)
    assert any(g[0] < 20 and g[1] <= 20.1 for g in gaps_keep)      # a gap before the beat's vocal
    assert any(g[0] >= 25 for g in gaps_keep)                       # and after it
    gaps_whole = rule3.instrumental_gaps(benv, sr, 40.0, keep_beat_vocal=False)
    assert gaps_whole == [(0.0, 40.0)]                              # vocal-heavy beat -> whole track


def test_schedule_fires_on_beat_downbeats_inside_gaps():
    sr = 100
    env = _env(sr, 40, [(10.0, 12.0), (14.0, 16.0)])
    vdb = [float(x) for x in range(0, 41, 2)]
    a_unit, c_unit = rule3.pick_blocks((10.0, 16.0), vdb, 120.0, env, sr, (10.0, 12.0), (10.0, 16.0))
    bdb = [float(x) for x in range(0, 41, 2)]
    gaps = [(0.0, 20.0), (25.0, 40.0)]
    hits = rule3.schedule(bdb, gaps, a_unit, c_unit, track_end=40.0, stride_secs=2.0)
    assert hits, "expected at least one chop scheduled"
    for h in hits:
        assert h.block in ("A", "C")
        assert 0 <= h.beat_db_index < len(bdb)
        t = bdb[h.beat_db_index]
        assert any(g0 <= t < g1 for g0, g1 in gaps)   # every fire lands inside an instrumental gap
    assert {h.block for h in hits} >= {"A"}           # weave includes the tease
