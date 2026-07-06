"""Tests for the render engine. These shell out to FFmpeg (as the real pipeline
does), so they build tiny synthetic stems and confirm the finished WAV is valid,
click-free-length-correct, and never clipping. workers/ lives at the repo root, so
we put it on the path before importing.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import render  # noqa: E402


def _tone(path, freq=220.0, secs=4.0, amp=0.4, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _stems(tmp_path):
    paths = {}
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f, secs=8.0)  # bed long enough to hold placements out to ~6s
        paths[name] = p  # "vocals" here is Song 1's own vocal stem (used for contrast)
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=8.0)
    return paths, vocal


def _plan(anchor=1.0, stretch=1.0, vocal_src=(0.0, 2.0), beat_breath=False, master_bpm=120.0):
    return types.SimpleNamespace(
        master_bpm=master_bpm, vocal_stretch=stretch, vocal_src=vocal_src,
        anchor=anchor, beat_breath=beat_breath,
    )


def _arr_plan(placements, breath=False):
    """A duck-typed arrangement plan. placements = [(anchor, (start,end), beat_breath), ...]."""
    return types.SimpleNamespace(
        master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=placements[0][1], anchor=placements[0][0], beat_breath=breath,
        placements=[types.SimpleNamespace(anchor=a, vocal_src=v, beat_breath=b)
                    for a, v, b in placements],
    )


def test_render_produces_valid_wav(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_plan(anchor=1.0, vocal_src=(0.0, 2.0)), stems, vocal, out)

    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == render.SR
    assert y.shape[1] == 2  # stereo
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= render._CEILING  # audible, never clipping
    assert len(y) / sr >= 1.0 + 2.0 - 0.05  # bed holds anchor + the ~2s vocal


def test_render_applies_time_stretch(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # a real (safe) stretch exercises the atempo path without warble
    render.render_mix(_plan(stretch=0.95, vocal_src=(0.0, 2.0)), stems, vocal, out)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert float(np.max(np.abs(y))) <= render._CEILING


def test_render_places_vocal_in_multiple_spots(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_arr_plan([(1.0, (0.0, 1.5), False), (4.0, (0.0, 1.5), False)]),
                      stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # both vocal windows carry more energy than the beat-only gap between them
    assert e(1.0, 2.5) > e(2.6, 3.9) and e(4.0, 5.5) > e(2.6, 3.9)


def test_beat_breath_ducks_the_bar_not_silences_it(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # anchor 2.0s, 120bpm -> one bar = 2.0s; the bar before is DUCKED, not dead air
    render.render_mix(_arr_plan([(2.0, (0.0, 1.0), True)], breath=True), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    bar_before = float(np.max(np.abs(y[int(0.2 * sr):int(1.9 * sr)])))
    assert bar_before > 1e-3  # NOT dead air (the M3 gap bug stays fixed)


def test_render_mixes_song1_vocal_in_contrast_span(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(1.0, (0.0, 1.5), False)])
    plan.s1_vocal_regions = [(4.0, 6.0)]  # Song 1's own vocal answers 4-6s
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    e = lambda a, b: float(np.mean(np.abs(y[int(a * sr):int(b * sr)])))
    # the contrast span carries more energy than the beat-only stretch just before it
    assert e(4.0, 6.0) > e(2.5, 3.9)


def test_render_sweep_opens_up_before_entry(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    plan = _arr_plan([(3.0, (0.0, 1.0), False)])  # 120bpm bar=2s -> sweep over 1.0-3.0s
    plan.placements[0].fx = "sweep_in"
    render.render_mix(plan, stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    hf = lambda a, b: float(np.mean(np.abs(np.diff(y[int(a * sr):int(b * sr)], axis=0))))
    # early part of the swept bar is muffled (low brightness), later part opens up
    assert hf(1.1, 1.6) < hf(2.4, 2.9)


def test_sweep_bed_leading_edge_is_continuous():
    t = np.linspace(0, 400, 4410, endpoint=False)
    mono = (0.5 * np.sin(2 * np.pi * 5 * t)).astype("float32")
    seg = np.stack([mono, mono], axis=1)  # stereo
    out = render._sweep_bed(seg, render.SR)
    assert abs(float(out[0, 0]) - float(seg[0, 0])) < 1e-6  # starts on the original -> no click


def test_guard_duration_caps_over_long_audio(monkeypatch):
    monkeypatch.setattr(render, "_MAX_DECODED_SECS", 1)  # pretend the cap is 1s
    too_long = np.zeros((2 * render.SR, 2), dtype="float32")  # 2s > 1s
    with pytest.raises(render.RenderError):
        render._guard_duration(too_long)


def test_render_rejects_nonpositive_tempo(tmp_path):
    stems, vocal = _stems(tmp_path)
    with pytest.raises(render.RenderError):
        render.render_mix(_plan(master_bpm=0.0), stems, vocal, tmp_path / "x.wav")


def test_render_clamps_negative_anchor(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    render.render_mix(_plan(anchor=-5.0), stems, vocal, out)  # must not crash
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    assert len(y) > 0
