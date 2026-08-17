"""Is this actually music with a pulse? A FREE, local gate in front of the paid calls.

WHY IT EXISTS. `/add` spends real money on every accepted file — Replicate stem separation plus the
cloud structure analyser, about 12 cents a song. A podcast, a voice note or a phone recording will
happily go through that whole pipeline, cost the money, and produce a "song" nobody can mix. The
catalogue's own `bpm_confidence` cannot be the gate: it is derived from the beat grid, and the beat
grid IS the paid call.

So this is deliberately crude and deliberately CHEAP: numpy only, no PyTorch (this machine is
Windows-ARM and cannot run audio ML locally at all), a few seconds on a normalised wav.

HOW IT WORKS. A spectral-flux onset envelope — how much the spectrum brightens frame to frame —
then autocorrelation of that envelope. Music repeats: a kick every half second shows up as a peak
at that lag AND at twice, three times, four times that lag. That last part is what does the work.

A FIRST ATTEMPT WAS MEASURED AND THROWN AWAY, which is why the comb is here. Scoring "the best
peak relative to the average of its band" looked reasonable and does not work at all: white noise
scored 3.21 and the quietest real song (Umbrella) scored 3.27, so the two populations overlapped
and the gate would have been decoration. For any noisy signal the largest of many random values
sits a few multiples above their mean by chance alone. Averaging the autocorrelation at the lag
and its first three multiples fixes it, because a random peak has nothing at its own multiples.

MEASURED, 2026-08-17 — all 118 catalogue songs against synthetic non-music:

    podcast / spoken word   0.001        weakest real song   0.072  (Someone You Loved)
    white noise             0.008        5th percentile      0.154
    voice note              0.055        median              0.373

TUNED LOOSE, ON PURPOSE. A wrongly rejected song costs a real person their upload and their
goodwill; a wrongly accepted one costs about 12 cents. The bar is set at 0.03 — well clear of a
podcast and of noise, and a bit over twice as far below the weakest song in the whole catalogue.

THE HONEST GAP: a fast, evenly-paced voice note scores 0.055 and would PASS. Moving the bar up to
catch it would put it within a whisker of a real sparse ballad, which is the expensive mistake.
This gate is here to catch a podcast, not to judge music.
"""

from __future__ import annotations

import logging

import numpy as np
import soundfile as sf

log = logging.getLogger("promptdj.beatcheck")

# The tempo range worth looking in. Wider than the catalogue's own house band on purpose — the
# question here is "is there a pulse at all", not "will it mix well".
_MIN_BPM = 50.0
_MAX_BPM = 220.0

# How much of the track to listen to, from the middle. Enough for a stable estimate, short enough
# to stay quick on a laptop.
_SECONDS = 60.0

_FRAME = 1024
_HOP = 512

# THE BAR. The score is the mean normalised autocorrelation at the best lag and its first three
# multiples — 0.0 is no pulse at all, 1.0 is a metronome. Set from measurement, not taste: see the
# module docstring for the two populations it sits between.
_MIN_SCORE = 0.03

# How many multiples of the candidate beat period to check. A real pulse recurs at all of them.
_COMB_TEETH = 4


def _onset_envelope(mono: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    """Half-wave-rectified spectral flux: how much the sound brightens, frame by frame."""
    n = 1 + max(0, (len(mono) - _FRAME) // _HOP)
    window = np.hanning(_FRAME)
    mags = np.empty((n, _FRAME // 2 + 1), dtype=np.float32)
    for i in range(n):
        seg = mono[i * _HOP : i * _HOP + _FRAME]
        if len(seg) < _FRAME:
            seg = np.pad(seg, (0, _FRAME - len(seg)))
        mags[i] = np.abs(np.fft.rfft(seg * window))
    # log magnitude: a kick under a loud mix still registers as a rise
    logmag = np.log1p(mags)
    flux = np.maximum(0.0, np.diff(logmag, axis=0)).sum(axis=1)
    return flux, sr / _HOP  # envelope, frames per second


def beat_score(wav_path) -> tuple[float, float]:
    """(score, bpm) for the strongest pulse found. score <= 1.0 means no periodicity at all.

    Never raises on musical content; an unreadable file raises whatever soundfile raises, which the
    caller turns into "could not read that as audio".
    """
    y, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    mono = y.mean(axis=1)
    want = int(_SECONDS * sr)
    if len(mono) > want:  # a centered slice — the musical heart, not the intro
        start = (len(mono) - want) // 2
        mono = mono[start : start + want]
    if len(mono) < _FRAME * 4:
        return 0.0, 0.0

    env, fps = _onset_envelope(mono, sr)
    if len(env) < 16 or not np.any(env):
        return 0.0, 0.0

    # Flatten the slow loudness arc so a long crescendo cannot look like periodicity.
    env = env - np.convolve(env, np.ones(16) / 16, mode="same")
    env = np.maximum(env, 0.0)
    if not np.any(env):
        return 0.0, 0.0

    env = (env - env.mean()) / (env.std() or 1.0)
    ac = np.correlate(env, env, mode="full")[len(env) - 1 :]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac = ac / ac[0]

    lo = max(1, int(fps * 60.0 / _MAX_BPM))
    hi = min(len(ac) - 1, int(fps * 60.0 / _MIN_BPM))
    if hi <= lo:
        return 0.0, 0.0

    band = ac[lo : hi + 1]
    lag = lo + int(np.argmax(band))
    # THE COMB. A real pulse recurs at the period AND its multiples; a peak that happened by chance
    # has nothing at its own multiples. This is the whole discriminator — see the module docstring.
    score = sum(float(ac[min(lag * k, len(ac) - 1)]) for k in range(1, _COMB_TEETH + 1)) / _COMB_TEETH
    return max(0.0, score), 60.0 * fps / lag


def has_a_steady_beat(wav_path) -> tuple[bool, float, float]:
    """(ok, score, bpm). False only when there is no periodic pulse worth calling music."""
    score, bpm = beat_score(wav_path)
    ok = score >= _MIN_SCORE
    log.info("beat pre-check: score %.2f (bar %.2f) bpm~%.0f -> %s",
             score, _MIN_SCORE, bpm, "music" if ok else "REJECTED")
    return ok, score, bpm
