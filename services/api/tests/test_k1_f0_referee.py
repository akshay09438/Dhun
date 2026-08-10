"""Acceptance tests for the K1 f0-referee fix (written BEFORE the implementation, independently).

The diagnosed bug (2026-08-10, hard-measured): K1 (validate.assert_key_shift) verifies a
pitch-shifted vocal by whole-stem CHROMA rotation. On speech-like vocals (rap/whisper) the
broadband noise dominates the chroma and does NOT move under a pitch shift, so a CORRECTLY
shifted vocal reads "rotation 0/1" with a decisive gap and K1 wrongly declines the mix —
while an independent f0 measurement proves the pitch engine correct.

The human-approved fix under test:
  1. assert_key_shift measures the actual voice-pitch shift FIRST via
     app.audio.f0.measured_shift_semitones; when measurable it PASSES iff
     |measured - claimed| <= 0.5 st, RAISES when the shift decisively did not land,
     and only falls back to the chroma logic when f0 is unmeasurable (None).
  2. assert_key_shift RAISES when |int(semitones)| > 2 (the hard ±2 pitch cap),
     checked before any audio is read.
  3. The mix route (_run_mix) NEVER-REFUSES on a referee failure after a nonzero
     shift: the mix still completes "ready" using the ORIGINAL (unshifted) vocal.

Expected state on CURRENT code (verified by running pytest before the fix lands):
  RED  : test_k1_passes_correctly_shifted_speech_like_vocal   (chroma false-decline — the bug)
  GREEN: test_k1_still_rejects_unshifted_audio_claimed_shifted (no-weakening guard, both sides)
  RED  : test_k1_rejects_shift_beyond_cap                      (no magnitude guard yet)
  GREEN: test_f0_module_measures_pure_shift                    (spec-lock on the shipped f0 module)
  RED  : test_mix_route_ships_native_key_when_referee_fails    (route declines instead of never-refuse)

Fully hermetic: numpy audio on disk, deterministic seeds, no network, no node, no real render.
"""

import numpy as np
import pytest
import soundfile as sf

from app.audio import f0, pitch
from app.planner import validate
from app.routes import mix as mix_route
from tests.test_mix_route import (SONG1, SONG2, _setup_pair, _spy_render_to,
                                  _use_tmp, client)

# ------------------------------------------------------------------ the speech-like fixture
# Tuned (2026-08-10, sweep on current code) so that BOTH hold at once:
#   - the chroma referee reads a DECISIVELY WRONG rotation on a correct +2 shift
#     (measured on current code: best rotation 1, claim-gap 0.292 > _K1_MIN_MARGIN 0.15 -> raises),
#   - the f0 tracker confidently measures the voice (+2.09 st over 209 voiced frames).
# Construction mirrors real speech: strong formant-shaped broadband noise (identical in both
# files — it does NOT move under a pitch shift, exactly like a rap vocal's consonants/breath)
# plus a weaker harmonic voice that DOES move. Deterministic seed throughout.

_SR = 22050
_SECS = 20.0
_F0_HZ = 200.0
_SEED = 20260810
_NOISE_RMS = 0.5
_HARM_AMPS = [0.6, 0.4]  # fundamental + 2nd harmonic — enough for autocorr voicing


def _formant_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """White noise spectrally shaped by fixed 'formant' bumps: broadband and un-pitched (its
    autocorrelation at singable-f0 lags is ~0, so the f0 tracker ignores it) but with a strong,
    stable chroma signature — the speech-like content that fools the chroma referee."""
    w = rng.standard_normal(n)
    spec = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n, 1 / _SR)
    env = 0.05 * np.ones_like(freqs)
    for fc, bw in [(1800.0, 300.0), (3300.0, 350.0), (5200.0, 400.0)]:
        env = env + np.exp(-0.5 * ((freqs - fc) / bw) ** 2)
    y = np.fft.irfft(spec * env, n)
    return y / (np.sqrt(np.mean(y**2)) + 1e-12)  # unit RMS


def _speech_like(tmp_path, name: str, f0_hz: float):
    """A speech-like 'vocal' WAV: the SAME seeded noise every call (a pitch shift moves the voice,
    not the noise) + a harmonic voice at f0_hz. Regenerating with f0_hz * 2**(2/12) IS the
    ground-truth correct +2 st shift of the voiced content."""
    rng = np.random.default_rng(_SEED)
    n = int(_SR * _SECS)
    t = np.arange(n) / _SR
    y = _NOISE_RMS * _formant_noise(n, rng)
    for k, a in enumerate(_HARM_AMPS, start=1):
        y = y + a * np.sin(2 * np.pi * k * f0_hz * t)
    path = tmp_path / name
    sf.write(str(path), y.astype("float32"), _SR)
    return path


# ------------------------------------------------------------- A. the false-decline bug itself

def test_k1_passes_correctly_shifted_speech_like_vocal(tmp_path):
    """A CORRECTLY +2-shifted speech-like vocal must PASS K1.

    RED on current code, for the diagnosed reason: the noise dominates the chroma and does not
    move, so best_rotation reads a wrong rotation (measured: rot 1) with a decisive claim-gap
    (measured: 0.292 > _K1_MIN_MARGIN 0.15) and assert_key_shift raises ValidationError — the
    exact false decline that wrongly refused real rap/whisper mixes. After the fix, the f0
    measurement (asserted ~+2 below, so this test can go green) settles it first: no raise."""
    orig = _speech_like(tmp_path, "orig.wav", _F0_HZ)
    shifted = _speech_like(tmp_path, "shifted.wav", _F0_HZ * 2 ** (2 / 12))

    # Fixture sanity (green now — f0.py already ships): the voice pitch measurably moved ~+2 st,
    # so after the fix K1's f0-first path will read this pair as CORRECT, not stay unmeasurable.
    measured = f0.measured_shift_semitones(orig, shifted)
    assert measured is not None, "fixture must be f0-measurable, or the fix could never pass it"
    semis, n_frames = measured
    assert abs(semis - 2.0) <= 0.3, f"fixture voice must read ~+2 st, got {semis:+.2f}"
    assert n_frames >= f0.MIN_VOICED_FRAMES, f"fixture must be confidently voiced, got {n_frames} frames"

    # The acceptance itself: a correct shift on speech-like material is NOT declined.
    try:
        validate.assert_key_shift(orig, shifted, semitones=2)
    except validate.ValidationError as e:
        pytest.fail(
            "K1 falsely declined a CORRECTLY +2-shifted speech-like vocal (the diagnosed "
            f"chroma-on-noise bug): {e}")


# ------------------------------------------------- B. no-weakening guard: a real fake still fails

def test_k1_still_rejects_unshifted_audio_claimed_shifted(tmp_path):
    """NO-WEAKENING GUARD: an UNSHIFTED vocal labelled +2 must RAISE both before AND after the fix.

    GREEN on current code (chroma reads rotation 0 vs claim 2, decisively). Its role: pin the
    referee's reason for existing while the fix lands — the f0 path must ALSO decline this
    (measured shift 0.0 vs claimed 2 -> |0 - 2| > 0.5), so the fix cannot 'solve' the false
    declines by simply trusting every shift. If this ever goes red, K1 was weakened, not fixed."""
    orig = _speech_like(tmp_path, "orig.wav", _F0_HZ)
    same = _speech_like(tmp_path, "same.wav", _F0_HZ)  # identical content — truly 0 st
    with pytest.raises(validate.ValidationError):
        validate.assert_key_shift(orig, same, semitones=2)


# --------------------------------------------------------------- C. the hard ±2 pitch cap in K1

def test_k1_rejects_shift_beyond_cap(tmp_path):
    """The hard ±2 pitch cap (founder rule 2026-08-10) must fire INSIDE the referee, before any
    audio is read — so no caller path (label rule, empirical fallback, a future bug) can ever
    ship a >|2| st vocal past K1. Nonexistent paths prove the check precedes the audio read.

    RED on current code: there is no magnitude guard in assert_key_shift — it goes straight to
    sf.read on the dummy path and raises a file-not-found error, not ValidationError."""
    from pathlib import Path

    for semis in (3, -3):
        with pytest.raises(validate.ValidationError):
            validate.assert_key_shift(Path("x.wav"), Path("y.wav"), semis)


# ------------------------------------------------- D. spec-lock on the shipped f0 measurement

def test_f0_module_measures_pure_shift(tmp_path):
    """Spec-lock on app.audio.f0.measured_shift_semitones (GREEN now — the module already ships):
    (a) a harmonic tone vs its +2 twin reads ~+2.0 st over a confident frame count, and
    (b) two pure-noise (unvoiced) files are UNMEASURABLE -> None, the exact contract the fixed
    referee relies on to fall back to chroma. Locks the interface the fix builds on."""
    def _tone(name, freq):
        t = np.arange(int(_SR * 8.0)) / _SR
        y = sum((1.0 / k) * np.sin(2 * np.pi * k * freq * t) for k in range(1, 5))
        p = tmp_path / name
        sf.write(str(p), (0.3 * y).astype("float32"), _SR)
        return p

    orig = _tone("tone.wav", 220.0)
    up2 = _tone("tone_up2.wav", 220.0 * 2 ** (2 / 12))
    measured = f0.measured_shift_semitones(orig, up2)
    assert measured is not None, "a clean harmonic +2 shift must be measurable"
    semis, n_frames = measured
    assert abs(semis - 2.0) <= 0.3, f"expected ~+2.0 st, measured {semis:+.2f}"
    assert n_frames >= 30, f"expected a confident reading (>=30 frames), got {n_frames}"

    def _noise(name, seed):
        y = 0.3 * np.random.default_rng(seed).standard_normal(int(_SR * 8.0))
        p = tmp_path / name
        sf.write(str(p), y.astype("float32"), _SR)
        return p

    assert f0.measured_shift_semitones(_noise("n1.wav", 1), _noise("n2.wav", 2)) is None, (
        "pure noise has no voice pitch — must be unmeasurable (None), the chroma-fallback trigger")


# ------------------------------------- E. the route never-refuses when the referee declines

def _poll_terminal(mix_id, tries=240):
    """Poll until the job reaches a terminal state (ready or error) — the file's established
    polling pattern, but terminal-state-aware so the current RED (error) returns fast."""
    import time
    body = {}
    for _ in range(tries):
        body = client.get(f"/mix/{mix_id}").json()
        if body["status"] in ("ready", "error"):
            return body
        time.sleep(0.05)
    return body


def test_mix_route_ships_native_key_when_referee_fails(tmp_path, monkeypatch):
    """NEVER-REFUSE (founder rule: no pair is ever un-mixable): when the K1 referee declines a
    nonzero shift, the mix must still complete "ready" — rendered with the ORIGINAL (unshifted)
    vocal, native key, instead of erroring out.

    RED on current code: _run_mix lets the referee's ValidationError fall through to the
    quality-failure handler, so the job ends status="error" ("didn't pass the quality check")
    and this poll returns error, never ready. After the fix the route catches the referee
    failure, swaps back to the original stem, and the render spy must receive it."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    shifted_path = tmp_path / "shifted_vocal.wav"
    t = np.linspace(0, 6.0, int(44100 * 6.0), endpoint=False)
    sf.write(str(shifted_path), (0.4 * np.sin(2 * np.pi * 500.0 * t)).astype("float32"), 44100)

    rendered = {}

    def failing_referee(original_vocal, shifted_vocal, semitones):
        raise validate.ValidationError(
            ["key-shift referee (K1): test-forced decisive decline"])

    monkeypatch.setattr(mix_route, "resolve_key_shift", lambda a1, a2: (2, "key-match test +2"))
    monkeypatch.setattr(pitch, "shifted_vocal",
                        lambda song_id, vocal_wav, semitones, formant=True: shifted_path)
    monkeypatch.setattr(mix_route.validate, "assert_key_shift", failing_referee)
    monkeypatch.setattr(mix_route, "render_mix", _spy_render_to(rendered))

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll_terminal(r.json()["mix_id"])

    assert body["status"] == "ready", (
        "a referee-declined key shift must NEVER refuse the mix — it must ship at the native "
        f"key instead; got status={body['status']!r} message={body.get('message')!r}")
    original_stem = str(tmp_path / f"{SONG2}.vocals.mp3")  # stem_path(SONG2, 'vocals') under tmp data_dir
    assert rendered.get("s2_voc") == original_stem, (
        "the render must receive the ORIGINAL (unshifted) vocal stem after a referee decline, "
        f"never the failed shifted one; render got {rendered.get('s2_voc')!r}")
    assert rendered.get("s2_voc") != str(shifted_path), (
        "the failed shifted vocal must not be rendered")


def test_key_shift_fallback_is_recorded_as_a_visible_anomaly(tmp_path, monkeypatch):
    """NEVER-REFUSE must never be SILENT: when a shift can't be verified and the mix falls back to the
    NATIVE key, the operator must see WHY. Guards the `key_shift_fallback` anomaly (severity 'warn'),
    which is the only signal separating 'shipped native on purpose' from 'silently shipped a clash'."""
    import json

    from app import events
    from app.planner.validate import ValidationError
    from tests.test_mix_route import _poll

    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    monkeypatch.setattr(mix_route, "resolve_key_shift", lambda a1, a2: (2, "needs +2"))
    monkeypatch.setattr(pitch, "shifted_vocal", lambda *a, **k: tmp_path / "dummy_shift.wav")
    monkeypatch.setattr(mix_route.validate, "assert_key_shift",
                        lambda *a, **k: (_ for _ in ()).throw(ValidationError(["forced decline"])))
    rendered: dict = {}
    monkeypatch.setattr(mix_route, "render_mix", _spy_render_to(rendered))

    mix_id = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2,
                                   "prompt": "anomaly-visibility"}).json()["mix_id"]
    assert _poll(mix_id, "ready")["status"] == "ready"

    rows = events.query_events(tmp_path)["events"]
    row = next(r for r in rows if r["ref_id"] == mix_id)
    anoms = row["anomalies"] or []
    if isinstance(anoms, str):  # the store may hand back raw JSON or a decoded list
        anoms = json.loads(anoms or "[]")
    codes = [a.get("code") for a in anoms]
    assert "key_shift_fallback" in codes, f"the native-key fallback must be visible; got {codes}"
    assert row["health"] == "amber", "a degraded (native-key) mix must not look clean-green"
