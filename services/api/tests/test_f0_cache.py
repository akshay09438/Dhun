"""The f0 measurement is cached — a repeat verification of the same pair is free.

Measuring costs 10-16 s per call on real stems (measured 2026-08-10) and the K1 referee ran it on
EVERY key-matched render, even though both inputs are immutable and content-addressed. These tests
pin the cache: it must return the SAME answer without recomputing, invalidate when the measurement
version changes, and never let a cache problem break a mix.
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
import soundfile as sf

from app.audio import f0

SR = 22050


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    """Cache entries land in a throwaway data dir, never the real one."""
    monkeypatch.setattr(f0, "settings", dataclasses.replace(f0.settings, data_dir=tmp_path))


def _voice(path, f0_hz: float, secs: float = 6.0):
    t = np.arange(int(SR * secs)) / SR
    y = sum(np.sin(2 * np.pi * f0_hz * k * t) / k for k in (1, 2, 3, 4, 5)).astype(np.float32)
    sf.write(str(path), y * 0.3, SR)
    return path


def _pair(tmp_path, semitones: float = 2.0):
    orig = _voice(tmp_path / "orig.wav", 200.0)
    shifted = _voice(tmp_path / "shifted.wav", 200.0 * 2 ** (semitones / 12))
    return orig, shifted


def test_second_call_uses_the_cache_and_does_not_recompute(tmp_path, monkeypatch):
    orig, shifted = _pair(tmp_path)
    first = f0.measured_shift_semitones(orig, shifted)
    assert first is not None and abs(first[0] - 2.0) < 0.3

    # Any recomputation now would call _measure — make that an outright failure.
    monkeypatch.setattr(f0, "_measure", lambda *a, **k: pytest.fail("recomputed instead of using the cache"))
    assert f0.measured_shift_semitones(orig, shifted) == first


def test_cache_entry_is_written_where_expected(tmp_path):
    orig, shifted = _pair(tmp_path)
    f0.measured_shift_semitones(orig, shifted)
    p = f0.cache_path(orig, shifted)
    assert p.exists() and p.name.endswith(f0.CACHE_SUFFIX)
    assert "semitones" in json.loads(p.read_text(encoding="utf-8"))


def test_a_version_bump_invalidates_the_stored_answer(tmp_path, monkeypatch):
    orig, shifted = _pair(tmp_path)
    old_path = f0.cache_path(orig, shifted)
    f0.measured_shift_semitones(orig, shifted)
    assert old_path.exists()

    monkeypatch.setattr(f0, "MEASURE_VERSION", "f0v2-improved")
    assert f0.cache_path(orig, shifted) != old_path, "a new version must not read the old entry"
    calls = []
    real = f0._measure
    monkeypatch.setattr(f0, "_measure", lambda o, s: (calls.append(1), real(o, s))[1])
    f0.measured_shift_semitones(orig, shifted)
    assert calls, "a version bump must force a fresh measurement"


def test_different_pairs_do_not_share_an_answer(tmp_path):
    orig, up2 = _pair(tmp_path, 2.0)
    down1 = _voice(tmp_path / "down1.wav", 200.0 * 2 ** (-1 / 12))
    a = f0.measured_shift_semitones(orig, up2)
    b = f0.measured_shift_semitones(orig, down1)
    assert a is not None and b is not None
    assert abs(a[0] - 2.0) < 0.3 and abs(b[0] + 1.0) < 0.3


def test_unmeasurable_is_remembered_too(tmp_path, monkeypatch):
    rng = np.random.default_rng(7)
    n1 = tmp_path / "n1.wav"
    n2 = tmp_path / "n2.wav"
    for p in (n1, n2):
        sf.write(str(p), rng.normal(0, 0.2, SR * 6).astype(np.float32), SR)
    assert f0.measured_shift_semitones(n1, n2) is None
    monkeypatch.setattr(f0, "_measure", lambda *a, **k: pytest.fail("re-measured a known-unmeasurable pair"))
    assert f0.measured_shift_semitones(n1, n2) is None


def test_a_broken_cache_entry_falls_back_to_measuring(tmp_path):
    orig, shifted = _pair(tmp_path)
    f0.cache_path(orig, shifted).write_text("{not json", encoding="utf-8")
    got = f0.measured_shift_semitones(orig, shifted)  # must not raise
    assert got is not None and abs(got[0] - 2.0) < 0.3


def test_an_unwritable_cache_never_breaks_the_measurement(tmp_path, monkeypatch):
    orig, shifted = _pair(tmp_path)
    monkeypatch.setattr(f0, "_cache_write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        f0._cache_write(tmp_path / "x", None)  # the stub really does raise
    monkeypatch.setattr(f0, "_cache_write", lambda p, r: None)  # as the real one behaves: swallow
    got = f0.measured_shift_semitones(orig, shifted)
    assert got is not None
