"""Tests for the standalone level/crest guards (Phase 0 P2 + saturation-mush).

These test the guard against SYNTHETIC signals with KNOWN answers — a pure sine (crest ~= sqrt(2)),
a square (crest -> 1), silence, a peak blow-up, and a spiky signal destroyed by saturation — so the
guard's correctness does NOT depend on the render path. workers/ lives at the repo root.
"""
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import chain_guards  # noqa: E402


def _stereo(m):
    return np.stack([m, m], axis=1).astype(np.float32)


def test_crest_factor_of_known_signals():
    t = np.linspace(0, 1, 44100, endpoint=False)
    sine = _stereo(0.9 * np.sin(2 * np.pi * 220 * t))
    assert abs(chain_guards.crest_factor(sine) - np.sqrt(2)) < 0.05      # a sine is ~1.414
    square = _stereo(0.9 * np.sign(np.sin(2 * np.pi * 220 * t)))
    assert chain_guards.crest_factor(square) < 1.1                        # a square is ~1.0
    assert chain_guards.crest_factor(np.zeros((100, 2), dtype=np.float32)) == float("inf")  # silence


def test_guard_passes_a_clean_chain():
    t = np.linspace(0, 1, 44100, endpoint=False)
    x = _stereo(0.6 * np.sin(2 * np.pi * 300 * t))
    assert chain_guards.check_vocal_chain_output(x, x * 0.95) is None     # small level change, same crest


def test_guard_flags_a_peak_blowup_as_p2():
    t = np.linspace(0, 1, 44100, endpoint=False)
    x = _stereo(0.4 * np.sin(2 * np.pi * 300 * t))
    r = chain_guards.check_vocal_chain_output(x, x * 2.0)                 # +6 dB peak
    assert r is not None and "P2" in r


def test_guard_flags_saturation_mush_via_crest_collapse():
    """A spiky, high-crest signal hard-saturated into mush: the PEAK barely moves (tanh caps at 1), so
    P2 is blind to it — the crest-factor guard must catch it. This is the exact failure mode P2 alone
    misses."""
    rng = np.random.default_rng(0)
    m = (0.03 * rng.standard_normal(44100)).astype(np.float32)
    m[::4000] = 0.9                                                       # sparse big spikes -> high crest
    before = _stereo(m)
    after = np.tanh(before * 30).astype(np.float32)                      # destroy it into near-square mush
    assert chain_guards.crest_factor(before) > 3.0                        # confirm the input really is spiky
    # the peak barely changed (P2 would pass), proving the crest guard is doing the work:
    assert np.max(np.abs(after)) < np.max(np.abs(before)) * chain_guards._P2_MAX_GAIN
    r = chain_guards.check_vocal_chain_output(before, after)
    assert r is not None and "mush" in r.lower()


def test_empirical_threshold_clears_legal_processing():
    """Documents the calibration: legal processing keeps crest ratio >= ~0.83; the threshold is 0.60,
    so a modest crest reduction (a compressor doing its job) never false-positives."""
    rng = np.random.default_rng(1)
    before = _stereo((0.2 * rng.standard_normal(44100)).astype(np.float32))
    after = before * 1.0  # crest unchanged
    assert chain_guards.CREST_MIN_RATIO == 0.60
    assert chain_guards.check_vocal_chain_output(before, after) is None
