"""Integration test for the Rule 3 renderer — runs the real DSP (ffmpeg) on synthetic audio.
Proves: a scheduled chop plan renders to a valid, non-silent, correct-length WAV with the chops
audible at the scheduled beat downbeats (and the bed present between them)."""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

_REPO = Path(__file__).resolve().parents[3]                    # repo root, for `workers`
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.planner.rule3 import ChopBlock, ChopHit, Rule3Plan  # noqa: E402
from workers.rule3 import render_rule3  # noqa: E402

SR = 44100


def _tone(path, secs, freq):
    t = np.linspace(0, secs, int(secs * SR), endpoint=False)
    y = 0.3 * np.sin(2 * np.pi * freq * t).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), SR)


def _rms(y):
    return float(np.sqrt(np.mean(np.asarray(y, np.float64) ** 2) + 1e-12))


def test_render_rule3_places_chops_on_the_grid(tmp_path):
    drums, bass, other = tmp_path / "d.wav", tmp_path / "b.wav", tmp_path / "o.wav"
    song1, vocal = tmp_path / "s1.wav", tmp_path / "voc.wav"
    for p, f in ((drums, 110), (bass, 60), (other, 330), (song1, 110)):
        _tone(p, 30.0, f)
    _tone(vocal, 20.0, 220)                     # a steady sung tone to chop from

    downbeats = [float(x) for x in range(0, 31, 2)]   # 120 BPM grid
    plan = Rule3Plan(
        a_unit=[ChopBlock(bars=((4.0, 6.0),), word_end=6.3)],           # tease, with a word-tail to fade
        c_unit=[ChopBlock(bars=((4.0, 6.0), (6.0, 8.0)), word_end=8.0)],  # full = two phrases
        hits=[ChopHit("A", 5), ChopHit("C", 10)],                        # fire at downbeats 10s and 20s
        keep_beat_vocal=False,                                           # use the stems as the bed
    )
    out = tmp_path / "mix.wav"
    render_rule3(plan, downbeats, 120.0, {"drums": drums, "bass": bass, "other": other}, song1, vocal, out)

    assert out.exists()
    y, sr = sf.read(str(out), always_2d=True)
    assert sr == SR
    assert abs(len(y) / SR - 30.0) < 0.2                 # length == the bed, not stretched
    assert float(np.max(np.abs(y))) > 0.05               # not silent
    m = y.mean(axis=1)

    def band(a, b, f=220.0):
        seg = m[int(a * SR):int(b * SR)]
        mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / SR)
        k = int(np.argmin(np.abs(freqs - f)))
        return float(np.max(mag[max(0, k - 3):k + 4]))

    def rms(a, b):
        return _rms(m[int(a * SR):int(b * SR)])

    # the vocal chop is a 220 Hz tone; the bed tones are 60/110/330 Hz -> 220 Hz marks the chop
    assert band(10.4, 11.6) > 5 * band(2.5, 3.7)         # A chop present at its downbeat (10s)
    assert band(20.4, 22.4) > 5 * band(2.5, 3.7)         # C chop present at its downbeat (20s)
    assert rms(2.5, 3.7) > 0.01                          # the bed still plays between chops
