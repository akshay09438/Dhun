"""Pitch EXECUTOR (app/audio/pitch.py) — the verified + cached vocal pitch-shifter.

These tests are HERMETIC by construction: `pitch._render_once` (the only thing that launches the node
Signalsmith subprocess) is ALWAYS monkeypatched, so nothing here touches node, ffmpeg, or the network.
What is proven:
  * the verify-then-cache path (two INDEPENDENT renders must be byte-identical before a result is trusted),
    and that a second call is a cache hit returning the same bytes;
  * the cache identity is airtight — the path changes when song_id / semitones / formant / HELPER_VERSION
    change, so a helper upgrade can never serve stale-engine audio;
  * semitones == 0 returns the ORIGINAL stem untouched (no cache written);
  * the LOUD-FAILURE contract: renders that never agree, and a helper that raises (timeout / crash), both
    raise PitchError — and the retry is BOUNDED (never infinite), so a flaky helper declines instead of
    hanging forever. A silent un-shifted "key-matched" mix is the outcome this whole module exists to
    prevent.
"""

import dataclasses

import numpy as np
import pytest
import soundfile as sf

from app.audio import pitch


def _use_tmp_data_dir(monkeypatch, tmp_path):
    """Redirect the module's data_dir to a throwaway tmp_path — cache files and the render workdir all
    land there, never in the real catalog."""
    monkeypatch.setattr(pitch, "settings", dataclasses.replace(pitch.settings, data_dir=tmp_path))


def _vocal(tmp_path, name="voc.wav", freq=220.0, secs=1.0, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    y = (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32")
    p = tmp_path / name
    sf.write(str(p), y, sr)
    return p


def _fixed_render(shape=(4410, 1)):
    """A deterministic fake render — every call returns the SAME array, so the two-renders-agree path
    trusts it on the second attempt."""
    arr = np.linspace(-0.5, 0.5, int(np.prod(shape)), dtype=np.float32).reshape(shape)

    def _render_once(y, sr, semitones, formant, workdir):
        return arr.copy()

    return _render_once


def test_two_agreeing_renders_are_cached_and_reused(monkeypatch, tmp_path):
    """The verify-then-cache path: two byte-identical renders publish a `.pitchshift.wav` cache file, and
    a SECOND call is a cache hit — same path, byte-identical content, and NO further render launches."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    voc = _vocal(tmp_path)
    calls = {"n": 0}
    base = _fixed_render()

    def counting(y, sr, semitones, formant, workdir):
        calls["n"] += 1
        return base(y, sr, semitones, formant, workdir)

    monkeypatch.setattr(pitch, "_render_once", counting)

    out1 = pitch.shifted_vocal("a" * 64, voc, semitones=2)
    assert out1.name.endswith(pitch.CACHE_SUFFIX), out1.name  # ends with .pitchshift.wav (the eviction key)
    assert out1.exists()
    assert calls["n"] == 2, "trust requires exactly two INDEPENDENT renders that agree"
    first_bytes = out1.read_bytes()

    out2 = pitch.shifted_vocal("a" * 64, voc, semitones=2)
    assert out2 == out1, "a second call must be a cache hit at the same path"
    assert calls["n"] == 2, "the cache hit must NOT launch the helper again"
    assert out2.read_bytes() == first_bytes, "cache hit must return byte-identical audio"


def test_cache_path_is_keyed_by_every_identity_field(monkeypatch, tmp_path):
    """AIRTIGHT cache identity: the path must differ when ANY of song_id / semitones / formant /
    HELPER_VERSION differ — bump one at a time and the path changes, so a helper upgrade never serves
    stale-engine audio and two different shifts never collide."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    base = pitch.cache_path("a" * 64, 2, True)

    assert pitch.cache_path("b" * 64, 2, True) != base       # different song_id
    assert pitch.cache_path("a" * 64, 3, True) != base       # different semitones
    assert pitch.cache_path("a" * 64, -2, True) != base      # different direction
    assert pitch.cache_path("a" * 64, 2, False) != base      # different formant flag

    monkeypatch.setattr(pitch, "HELPER_VERSION", pitch.HELPER_VERSION + "-bumped")
    assert pitch.cache_path("a" * 64, 2, True) != base, "a HELPER_VERSION bump must invalidate the path"


def test_zero_semitones_returns_the_original_untouched(monkeypatch, tmp_path):
    """semitones == 0 -> the ORIGINAL stem path, unchanged, and NO cache file written. The un-shifted
    path must never fabricate a pitchshift file or launch the helper."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    voc = _vocal(tmp_path)

    def boom(*a, **k):
        raise AssertionError("_render_once must not be called at semitones == 0")

    monkeypatch.setattr(pitch, "_render_once", boom)

    out = pitch.shifted_vocal("a" * 64, voc, semitones=0)
    assert out == voc, "zero shift must return the original vocal path"
    assert not list(tmp_path.glob(f"*{pitch.CACHE_SUFFIX}")), "no cache file may be written at zero shift"


def test_non_agreeing_renders_raise_after_a_bounded_retry(monkeypatch, tmp_path):
    """LOUD FAILURE (required): a helper that returns a DIFFERENT array every call can never get two to
    agree — so shifted_vocal must raise PitchError after a BOUNDED number of attempts (never loop
    forever), and never publish a cache file. Asserts the retry count is exactly _MAX_ATTEMPTS."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    voc = _vocal(tmp_path)
    calls = {"n": 0}

    def ever_changing(y, sr, semitones, formant, workdir):
        calls["n"] += 1
        # Same SHAPE each time (so array_equal actually compares values), different CONTENT -> never agree.
        return np.full((4410, 1), float(calls["n"]), dtype=np.float32)

    monkeypatch.setattr(pitch, "_render_once", ever_changing)

    with pytest.raises(pitch.PitchError):
        pitch.shifted_vocal("a" * 64, voc, semitones=2)
    assert calls["n"] == pitch._MAX_ATTEMPTS, (
        f"retry must be bounded to _MAX_ATTEMPTS ({pitch._MAX_ATTEMPTS}), got {calls['n']}")
    assert not list(tmp_path.glob(f"*{pitch.CACHE_SUFFIX}")), "a non-verified render must never be cached"


def test_helper_error_propagates_as_pitch_error(monkeypatch, tmp_path):
    """LOUD FAILURE (required): if the helper itself raises (a crash / timeout surfaces as PitchError
    from _render_once), that propagates straight out of shifted_vocal — the mix DECLINES visibly, it
    never falls back to shipping un-shifted audio. No cache is written."""
    _use_tmp_data_dir(monkeypatch, tmp_path)
    voc = _vocal(tmp_path)

    def timeout(y, sr, semitones, formant, workdir):
        raise pitch.PitchError("pitch helper hung (> 180s) — declining")

    monkeypatch.setattr(pitch, "_render_once", timeout)

    with pytest.raises(pitch.PitchError):
        pitch.shifted_vocal("a" * 64, voc, semitones=2)
    assert not list(tmp_path.glob(f"*{pitch.CACHE_SUFFIX}")), "a failed render must never be cached"
