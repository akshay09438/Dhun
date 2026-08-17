"""Is this actually music with a pulse? A FREE, local COURTESY FILTER in front of the paid calls.

THIS IS NOT A SECURITY CONTROL, and it is important that nobody later mistakes it for one.

Its job is to stop an ACCIDENT costing money: somebody attaches a podcast, a voice note or the
wrong file, and it is refused in seconds instead of paying about 12 cents to separate speech into
four stems. It does that well.

It cannot stop somebody who is TRYING. Two rounds of the security review beat it twice — first with
a tick over silence, then, after a density gate was added, with the same tick over a quiet drone
(260 KB, straight through both gates). Neither gate looks at timbre, harmony or spectral variety,
so the whole bar is "periodic and not silent", and both are trivially synthesised. Tuning it
against each new crafted payload is an arms race with no end, and every turn of it risks the
expensive mistake in the other direction: rejecting a real song somebody made.

**The real defence against a hostile uploader is `app/spend.py`** — a hard, durable ceiling on how
many paid attempts can ever happen, counted across everybody, successes and failures alike. That
bounds the bill no matter what the file is. Founder's call, 2026-08-17: leave the threshold, write
the limitation down, move on.

So the bar below stays where the MEASUREMENT put it (0 of 118 real songs rejected) and is not to be
raised chasing a crafted sample — raising it costs real uploads and buys nothing.


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

# THE SECOND GATE: how much of the track is actually SOUNDING.
#
# The comb alone is beaten by the cheapest possible payload — eight minutes of near-silence with a
# tick every half second scores 0.86-0.90, because it is perfectly periodic. It is also a few tens
# of KB, so it uploads instantly, which made it the ideal way to drive requests at the paid
# pipeline (2026-08-17 security review). Periodicity is necessary for music; it is not sufficient.
#
# Music is DENSE: nearly every 20 ms of it is within 40 dB of the track's loudest moment. A ticker
# over silence is not. Measured over all 118 catalogue songs against the attack:
#
#     silence + ticker (three variants)  0.040
#     weakest real song (Bad Guy)        0.909
#     median real song                   1.000
#
# Bar at 0.35 — nine times clear of the attack, and well under half the weakest real song. A first
# attempt measured the level against the 95th percentile and scored the attack 1.000, because on a
# sparse tick track the 95th percentile IS the silence; the peak is the right reference.
_MIN_ACTIVITY = 0.35
_ACTIVITY_FLOOR_DB = 0.01     # -40 dB relative to the loudest frame
_ACTIVITY_HOP_S = 0.02


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


def activity(wav_path) -> float:
    """Share of the track within 40 dB of its own loudest moment. ~1.0 for music, ~0 for a ticker
    over silence. See _MIN_ACTIVITY for why the reference is the PEAK and not a percentile."""
    y, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    mono = y.mean(axis=1)
    want = int(_SECONDS * sr)
    if len(mono) > want:
        start = (len(mono) - want) // 2
        mono = mono[start : start + want]
    hop = max(1, int(sr * _ACTIVITY_HOP_S))
    n = len(mono) // hop
    if n < 10:
        return 0.0
    rms = np.sqrt(np.array([np.mean(mono[i * hop : (i + 1) * hop] ** 2) for i in range(n)]) + 1e-12)
    loudest = float(rms.max())
    if loudest <= 0:
        return 0.0
    return float(np.mean(rms > loudest * _ACTIVITY_FLOOR_DB))


def has_a_steady_beat(wav_path) -> tuple[bool, float, float]:
    """(ok, score, bpm). False when there is no periodic pulse, OR when the track is mostly silence.

    BOTH gates are needed. Periodicity alone is satisfied by a tick over silence, which is the
    cheapest file anyone could upload and therefore the best way to drive the paid pipeline.
    """
    score, bpm = beat_score(wav_path)
    act = activity(wav_path)
    ok = score >= _MIN_SCORE and act >= _MIN_ACTIVITY
    why = "music" if ok else ("REJECTED: too little sound" if act < _MIN_ACTIVITY
                              else "REJECTED: no pulse")
    log.info("beat pre-check: pulse %.3f (bar %.2f) density %.3f (bar %.2f) bpm~%.0f -> %s",
             score, _MIN_SCORE, act, _MIN_ACTIVITY, bpm, why)
    return ok, score, bpm
