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
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0)):
        p = tmp_path / f"{name}.wav"
        _tone(p, freq=f)
        paths[name] = p
    vocal = tmp_path / "vocal.wav"
    _tone(vocal, freq=440.0, secs=6.0)
    return paths, vocal


def _plan(anchor=1.0, stretch=1.0, vocal_src=(0.0, 2.0), beat_breath=False, master_bpm=120.0):
    return types.SimpleNamespace(
        master_bpm=master_bpm, vocal_stretch=stretch, vocal_src=vocal_src,
        anchor=anchor, beat_breath=beat_breath,
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


def test_beat_breath_silences_the_bar_before_entry(tmp_path):
    stems, vocal = _stems(tmp_path)
    out = tmp_path / "mix.wav"
    # anchor 2.0s, 120bpm -> one bar = 2.0s, so the whole first 2s should be silenced
    render.render_mix(_plan(anchor=2.0, beat_breath=True), stems, vocal, out)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    assert float(np.max(np.abs(y[: int(1.9 * sr)]))) < 1e-3  # near-silent breath


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
