"""Half-time pairing flag — a ~2x tempo pair is reported (never refused).

Silence (143 BPM) x Panda (72 BPM) locks perfectly on the beat via the octave fold, but the beat
pulses twice as often as the vocal, which the founder heard as "too fast" (2026-08-10). The mix is
still made; this flag records WHY it can feel off, so a human can prefer a closer-tempo partner.
"""
from __future__ import annotations

from app.planner import anomaly

_BASE = dict(grid_health={}, tempo_forced=False, vocal_stretch=1.0, key_why="")


def _codes(**kw) -> list[str]:
    return [a.code for a in anomaly.scan(**{**_BASE, **kw})]


def test_flags_the_real_silence_x_panda_pair():
    codes = _codes(beat_bpm=143.0, vocal_bpm=72.0)
    assert "half_time_pair" in codes


def test_flags_the_reverse_direction_too():
    # a slow beat under a double-time vocal is the same fold, the other way round
    assert "half_time_pair" in _codes(beat_bpm=72.0, vocal_bpm=143.0)


def test_does_not_flag_a_normal_close_tempo_pair():
    # Hey Brother 125 x Hum Pyaar Karne Wale 125, and a within-band 125 x 111
    assert "half_time_pair" not in _codes(beat_bpm=125.0, vocal_bpm=125.0)
    assert "half_time_pair" not in _codes(beat_bpm=125.0, vocal_bpm=111.0)


def test_silent_when_a_bpm_is_missing():
    assert "half_time_pair" not in _codes(beat_bpm=0.0, vocal_bpm=72.0)
    assert "half_time_pair" not in _codes()


def test_flag_is_a_warning_and_reports_both_tempos():
    (a,) = [x for x in anomaly.scan(**_BASE, beat_bpm=143.0, vocal_bpm=72.0)
            if x.code == "half_time_pair"]
    assert a.severity == "warn"
    assert "143" in a.detail and "72" in a.detail
    assert a.action  # tells a human what to do about it


def test_flagging_never_refuses_the_mix():
    # scan() is REPORT-ONLY: it returns anomalies, it cannot decline anything.
    out = anomaly.scan(**_BASE, beat_bpm=143.0, vocal_bpm=72.0)
    assert all(isinstance(x, anomaly.Anomaly) for x in out)
