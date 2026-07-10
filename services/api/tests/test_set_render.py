"""Tests for the set-assembly engine: joins finished mix WAVs into one continuous
"set" with equal-power crossfade transitions at each seam. Pure numpy/soundfile
(inputs are already WAVs, no ffmpeg needed) — mirrors test_render.py's style and
synthetic-tone approach. workers/ lives at the repo root, so we put it on the path
before importing.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import set_render  # noqa: E402


def _tone(path, freq=220.0, secs=4.0, amp=0.4, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (amp * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


def _dominant_freq(mono: np.ndarray, sr: int) -> float:
    mag = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
    return float(freqs[int(np.argmax(mag))])


def test_two_mix_set_length(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, freq=220.0, secs=5.0)
    _tone(b, freq=440.0, secs=5.0)
    out = tmp_path / "set.wav"
    set_render.assemble_set([a, b], out, xfade_secs=2.0)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert abs(dur - 8.0) < 0.05  # 5 + 5 - 2 (one seam)


def test_seam_is_continuous_no_gap(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, freq=220.0, secs=5.0, amp=0.5)
    _tone(b, freq=330.0, secs=5.0, amp=0.5)
    out = tmp_path / "set.wav"
    set_render.assemble_set([a, b], out, xfade_secs=2.0)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    # seam sits at output time [3.0, 5.0) (5s clip, 2s xfade -> seam starts at 5-2=3)
    seam = y[int(2.9 * sr):int(5.1 * sr)]
    mono = np.abs(seam).mean(axis=1)
    # no silent gap: no long contiguous near-zero span inside the seam region
    near_zero = mono < 1e-4
    # find the longest run of near-zero samples
    max_run, run = 0, 0
    for z in near_zero:
        run = run + 1 if z else 0
        max_run = max(max_run, run)
    assert max_run < int(0.01 * sr)  # never more than 10ms of near-silence
    # no hard click: sample-to-sample deltas across the seam stay bounded (no spike)
    d = np.abs(np.diff(y[int(2.9 * sr):int(5.1 * sr)], axis=0))
    steady = np.abs(np.diff(y[int(0.5 * sr):int(1.5 * sr)], axis=0))  # a steady, un-faded stretch
    assert float(np.max(d)) <= 3.0 * float(np.max(steady)) + 1e-6


def test_equal_power_no_volume_dip(tmp_path):
    """Equal-power crossfade preserves RMS across the seam for uncorrelated equal-amplitude
    content — sin^2+cos^2=1 keeps total power constant. A naive LINEAR (equal-gain) crossfade
    would dip to ~0.707x at the midpoint for the same inputs, so this genuinely distinguishes
    equal-power from a linear fade rather than being a tautology."""
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, freq=300.0, secs=5.0, amp=0.4)   # different, non-harmonic frequencies -> ~uncorrelated
    _tone(b, freq=733.0, secs=5.0, amp=0.4)
    out = tmp_path / "set.wav"
    set_render.assemble_set([a, b], out, xfade_secs=2.0)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    rms = lambda seg: float(np.sqrt(np.mean(seg.astype(np.float64) ** 2)))
    # seam occupies output [3.0, 5.0); midpoint ~4.0s
    mid = rms(y[int(3.85 * sr):int(4.15 * sr)])
    outside = rms(y[int(1.0 * sr):int(1.3 * sr)])  # pure clip-a region, before the seam
    assert mid >= 0.9 * outside, f"volume dipped at the seam: mid={mid:.4f} outside={outside:.4f}"


def test_never_clips(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, freq=220.0, secs=4.0, amp=0.97)  # hot, near full-scale
    _tone(b, freq=440.0, secs=4.0, amp=0.97)
    out = tmp_path / "set.wav"
    set_render.assemble_set([a, b], out, xfade_secs=1.5)
    y, _ = sf.read(out, dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(y)))
    assert 0.0 < peak <= set_render._CEILING


def test_single_mix_passthrough_length(tmp_path):
    a = tmp_path / "a.wav"
    _tone(a, freq=220.0, secs=5.0)
    out = tmp_path / "set.wav"
    set_render.assemble_set([a], out, xfade_secs=2.0)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert abs(dur - 5.0) < 0.05  # unchanged length, only the peak-normalize applied


def test_three_mix_set_order_and_length(tmp_path):
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    _tone(a, freq=200.0, secs=4.0, amp=0.5)
    _tone(b, freq=500.0, secs=5.0, amp=0.5)
    _tone(c, freq=900.0, secs=3.0, amp=0.5)
    out = tmp_path / "set.wav"
    xfade = 1.0
    set_render.assemble_set([a, b, c], out, xfade_secs=xfade)
    y, sr = sf.read(out, dtype="float32", always_2d=True)
    dur = len(y) / sr
    assert abs(dur - (4.0 + 5.0 + 3.0 - 2 * xfade)) < 0.05  # sum - 2 seams

    def dom_at(center_s):
        w = y[int((center_s - 0.25) * sr):int((center_s + 0.25) * sr)]
        mono = w.mean(axis=1)
        return _dominant_freq(mono, sr)

    # pure-a region [0, 3.0); pure-b region [4.0, 8.0); pure-c region [9.0, 10.0)
    assert abs(dom_at(1.0) - 200.0) < 15.0
    assert abs(dom_at(6.0) - 500.0) < 15.0
    assert abs(dom_at(9.5) - 900.0) < 15.0


def test_empty_list_raises(tmp_path):
    out = tmp_path / "set.wav"
    with pytest.raises(set_render.SetRenderError):
        set_render.assemble_set([], out)


# ---- 3.2: one global master tempo across a set ----

def test_set_tempo_band_matches_fence():
    """The set engine's safe band MUST equal the planner's SAFE_STRETCH band — one source of truth,
    two readers. If fence retunes the band, this fails loudly instead of the set drifting silently."""
    from app.planner import fence
    assert set_render.SAFE_STRETCH_LO == fence.SAFE_STRETCH_LO
    assert set_render.SAFE_STRETCH_HI == fence.SAFE_STRETCH_HI


def test_global_master_tempo_centres_every_song_in_the_band():
    """The chosen tempo keeps every song's stretch strictly inside [0.89, 1.11]."""
    bpms = [111.0, 118.0, 122.0, 125.0, 133.0]  # a feasible spread (max/min = 1.198 <= 1.247)
    t = set_render.global_master_tempo(bpms)
    assert 118.0 <= t <= 124.0
    for b in bpms:
        assert set_render.SAFE_STRETCH_LO <= t / b <= set_render.SAFE_STRETCH_HI
    assert set_render.global_master_tempo([]) == 0.0


def test_set_tempo_plan_all_fit_when_close():
    """A tempo-close set: one global tempo, nobody declined."""
    songs = [{"id": "a", "bpm": 120.0}, {"id": "b", "bpm": 124.0}, {"id": "c", "bpm": 118.0}]
    plan = set_render.set_tempo_plan(songs)
    assert plan["all_fit"] and not plan["declined"]
    assert all(0.89 <= s["ratio"] <= 1.11 for s in plan["accepted"])


def test_set_tempo_plan_declines_the_outlier_not_the_whole_set():
    """The 6-song catalog can't all share one tempo (111 & 143 BPM are >1.25x apart). The plan must
    DECLINE the single true outlier (Tere Bina, 143) and keep the other five in band — never loosen
    the band, and never wrongly drop a song that would have fit (e.g. Der Lagi, 111)."""
    songs = [
        {"name": "Father Ocean", "bpm": 122.0}, {"name": "Dont Start Now", "bpm": 125.0},
        {"name": "Der Lagi", "bpm": 111.0}, {"name": "Tujhe Bhula Diya", "bpm": 133.0},
        {"name": "With You", "bpm": 118.0}, {"name": "Tere Bina", "bpm": 143.0},
    ]
    plan = set_render.set_tempo_plan(songs)
    assert not plan["all_fit"]
    assert [d["name"] for d in plan["declined"]] == ["Tere Bina"]     # only the true outlier
    assert {a["name"] for a in plan["accepted"]} == {
        "Father Ocean", "Dont Start Now", "Der Lagi", "Tujhe Bhula Diya", "With You"}
    for a in plan["accepted"]:                                        # everyone kept is in band
        assert 0.89 <= a["ratio"] <= 1.11
    assert plan["declined"][0]["ratio"] < 0.89                        # Tere Bina really was out
