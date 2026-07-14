"""The set-assembly engine: join finished mix WAVs into one continuous "set" with
equal-power crossfade transitions at each seam.

Deterministic DSP only — numpy mixes, soundfile decodes/encodes. Inputs are already
rendered WAVs (see render.py), so no FFmpeg decode is needed here; this module stays
self-contained and does not import from render.py (it defines its own constants).

The transition, at each seam:
  - mix N's tail overlaps mix N+1's head for `xfade_secs`.
  - mix N's last `xf` samples fade OUT on a cosine curve, mix N+1's first `xf` samples
    fade IN on a sine curve, and the two are summed in the overlap. Because
    sin^2(t)+cos^2(t)=1, this is an EQUAL-POWER crossfade: total energy across the seam
    stays constant for the (uncorrelated) content of two different mixes, so there is no
    perceived volume dip the way a naive linear (equal-gain) fade would produce.
  - after every mix is joined, the whole set is peak-normalized to -1 dBFS and clipped to
    a safety ceiling, so a set can never clip — the same guarantee render.py gives a
    single mix.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100  # everything renders at CD rate, stereo
_TARGET_PEAK = 10 ** (-1.0 / 20)  # -1 dBFS headroom
_CEILING = 0.999  # brickwall safety — must stay below the validator's clip ceiling

# The safe SUSTAINED stretch band for a whole set — MUST match fence.SAFE_STRETCH_LO/HI (0.89–1.11);
# a drift test (test_set_render) pins them equal. A song whose stretch to the set tempo lands outside
# this warbles, so we DECLINE it rather than loosen the band (a warbling vocal is unrecoverable; a
# shorter set is invisible). Duplicated here on purpose so the set engine stays self-contained.
SAFE_STRETCH_LO = 0.89
SAFE_STRETCH_HI = 1.11


class SetRenderError(Exception):
    """Raised when the set-assembly engine cannot produce a set."""


# ---- SET PLANNING (the "brain": ONE master tempo for the whole set) -----------------------------
# 3.2: a real DJ set runs at one tempo. Decide it up front, before any mix renders, so every seam is
# a match of equal-length bars. Each song must land inside the safe stretch band at that tempo; one
# that can't is declined (or used partially) — the band is never loosened.


def _geo_mean(xs: list[float]) -> float:
    """Geometric mean — the right centre for a MULTIPLICATIVE stretch ratio (tempo/bpm)."""
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def global_master_tempo(bpms: list[float],
                        lo: float = SAFE_STRETCH_LO, hi: float = SAFE_STRETCH_HI) -> float:
    """ONE tempo for a set, centred so every song's stretch (tempo/bpm) sits as far as possible from
    a band edge. The tempos that keep EVERY song in [lo,hi] are the interval [max_bpm·lo, min_bpm·hi];
    return its geometric midpoint. Assumes the set is already feasible (max_bpm/min_bpm ≤ hi/lo) —
    `set_tempo_plan` drops outliers first. Returns 0.0 for an empty set."""
    xs = [b for b in bpms if b and b > 0]
    if not xs:
        return 0.0
    return round(((max(xs) * lo) * (min(xs) * hi)) ** 0.5, 2)


def set_tempo_plan(songs: list[dict],
                   lo: float = SAFE_STRETCH_LO, hi: float = SAFE_STRETCH_HI) -> dict:
    """Decide the set's single master tempo and which songs must be DECLINED to hold the safe band.

    `songs`: dicts carrying at least `bpm` (e.g. {"id","name","bpm"}); other keys pass through. A set
    is feasible at one tempo iff max_bpm/min_bpm ≤ hi/lo (≈1.25); while it isn't, drop the single
    worst OUTLIER — the min- or max-BPM song farthest (in log-tempo) from the running geometric mean —
    then centre the tempo on what's kept. Never loosens the band.

    Returns {"tempo", "accepted":[{...,"ratio"}], "declined":[{...,"ratio"}], "all_fit": bool}, where
    each `ratio` is the song's stretch at the FINAL tempo (so a decline says how far out it was)."""
    keep = [dict(s) for s in songs if s.get("bpm") and s["bpm"] > 0]
    declined: list[dict] = []

    def feasible(ss: list[dict]) -> bool:
        bs = [s["bpm"] for s in ss]
        return len(bs) <= 1 or max(bs) / min(bs) <= hi / lo + 1e-9

    while len(keep) > 1 and not feasible(keep):
        gm = _geo_mean([s["bpm"] for s in keep])
        worst = max(keep, key=lambda s: abs(math.log(s["bpm"]) - math.log(gm)))  # the far extreme
        keep = [s for s in keep if s is not worst]
        declined.append(worst)

    tempo = global_master_tempo([s["bpm"] for s in keep]) if keep else 0.0

    def ratio(s: dict):
        return round(tempo / s["bpm"], 3) if tempo else None

    return {
        "tempo": tempo,
        "accepted": [{**s, "ratio": ratio(s)} for s in keep],
        "declined": [{**s, "ratio": ratio(s)} for s in declined],
        "all_fit": not declined,
    }


def _decode(path: Path) -> np.ndarray:
    """Read a WAV to stereo float32 (mono files are tiled to 2 channels). Inputs are
    assumed to already be at SR — no resampling is attempted."""
    y, _ = sf.read(path, dtype="float32", always_2d=True)
    if y.shape[1] == 1:
        y = np.tile(y, (1, 2))
    return y


def _crossfade_join(a: np.ndarray, b: np.ndarray, xf: int) -> np.ndarray:
    """Join `a` then `b`, overlapping the last `xf` samples of `a` with the first `xf`
    samples of `b` via an equal-power crossfade. `xf` must already be clamped to at most
    half the shorter of the two clips (the caller does this)."""
    if xf <= 0:
        return np.vstack([a, b])
    t = np.linspace(0.0, 1.0, xf, dtype=np.float32)[:, None]
    fade_out = np.cos(t * np.pi / 2)  # a's tail: 1 -> 0
    fade_in = np.sin(t * np.pi / 2)   # b's head: 0 -> 1 (equal-power pair, sin^2+cos^2=1)
    head = a[:-xf]
    overlap = a[-xf:] * fade_out + b[:xf] * fade_in
    tail = b[xf:]
    return np.vstack([head, overlap, tail])


def assemble_set(mix_wavs: list[Path], out_path: Path, xfade_secs: float = 4.0) -> Path:
    """Join `mix_wavs` (already-rendered mix WAVs, in order) into one continuous set at
    `out_path`, crossfading `xfade_secs` at each seam, and return `out_path`.

    A single mix passes through unchanged except for the closing peak-normalize. An
    empty list is a caller error (nothing to assemble) and raises SetRenderError.
    `xfade_secs <= 0` produces a hard cut (plain concatenation, no crossfade).
    """
    if not mix_wavs:
        raise SetRenderError("no mixes to assemble a set from")

    clips = [_decode(p) for p in mix_wavs]
    y = clips[0]
    for nxt in clips[1:]:
        xf = int(SR * xfade_secs) if xfade_secs > 0 else 0
        xf = max(0, min(xf, len(y) // 2, len(nxt) // 2))
        y = _crossfade_join(y, nxt, xf)

    return _finalize(y, out_path)


def _finalize(y: np.ndarray, out_path: Path) -> Path:
    """Peak-normalize to −1 dBFS and brickwall-clip below the validator's ceiling, then write. THE
    clip-safety guarantee for every set (3.4): `assemble_set` and `assemble_beatmatched_set` share it,
    so neither can ship a clipping set no matter how the seams sum."""
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.0:
        y = y * (_TARGET_PEAK / peak)
    np.clip(y, -_CEILING, _CEILING, out=y)
    sf.write(out_path, y, SR, subtype="PCM_16")
    return out_path


# ---- SET ASSEMBLY (the "engine"): BEAT-ALIGNED, phrase-boundary seams (3.3) ----------------------


def _phrase_seam(a_ps: list[float], a_dur: float, b_ps: list[float], phrases: int,
                 ) -> tuple[float, float, float] | None:
    """Where the beat-aligned seam sits between outgoing mix A and incoming mix B, as
    (a_end_secs, b_start_secs, xf_secs) — or None to fall back to a plain timed crossfade.

    - a_end   = the LAST phrase boundary at/before A ends → mix OUT on A's final phrase;
    - a_start = `phrases` phrases earlier → the crossfade is A's last `phrases`×8 bars;
    - b_start = the FIRST phrase boundary of B → mix IN on B's opening phrase.
    Both crossfade regions begin on a phrase boundary (= a downbeat); with the whole set on ONE tempo
    (3.2) the bars are equal length, so every beat inside the overlap coincides — beat-aligned by
    construction, no onset detection. None when a grid can't spare a full `phrases`-phrase crossfade."""
    a = sorted(p for p in a_ps if 0.0 <= p <= a_dur + 1e-6)
    b = sorted(p for p in b_ps if p >= -1e-6)
    if len(a) < phrases + 1 or not b:
        return None
    a_end, a_start, b_start = a[-1], a[-1 - phrases], b[0]
    xf = a_end - a_start
    return (a_end, b_start, xf) if xf > 0 else None


def assemble_beatmatched_set(mixes: list[dict], out_path: Path, phrases: int = 1,
                             fallback_xfade_secs: float = 4.0) -> Path:
    """Join finished mixes into a set with BEAT-ALIGNED, phrase-boundary crossfades.

    `mixes`: in play order, each a dict {"wav": Path, "phrase_starts": [secs…]} (a mix's persisted
    `out_phrase_starts` from 3.1). Assumes every mix shares ONE master tempo (3.2), so equal bar
    lengths make the seam a plain phrase overlap: A's last `phrases`×8 bars fade out over B's first
    `phrases`×8 bars, both starting on a phrase boundary so the beats line up (never a mid-sentence
    cut). A seam whose grids can't support that falls back to a plain `fallback_xfade_secs` equal-power
    crossfade — never worse than `assemble_set`. Peak-safe via the shared `_finalize` (3.4). An empty
    list raises SetRenderError."""
    if not mixes:
        raise SetRenderError("no mixes to assemble a set from")

    clips = [_decode(m["wav"]) for m in mixes]
    y = clips[0]
    y_ps = list(mixes[0].get("phrase_starts") or [])   # the tail mix's phrase boundaries, in OUTPUT time
    for i in range(1, len(mixes)):
        nxt = clips[i]
        nxt_ps = list(mixes[i].get("phrase_starts") or [])
        seam = _phrase_seam(y_ps, len(y) / SR, nxt_ps, phrases)
        if seam is None:  # grids too thin -> plain timed crossfade (never worse than assemble_set)
            a, b = y, nxt
            xf = int(SR * fallback_xfade_secs) if fallback_xfade_secs > 0 else 0
            b_skip_s = 0
        else:
            a_end, b_start, xf_t = seam
            a = y[: int(round(a_end * SR))]
            b_skip_s = int(round(b_start * SR))
            b = nxt[b_skip_s:]
            xf = int(round(xf_t * SR))
        xf = max(0, min(xf, len(a) // 2, len(b) // 2))
        b_out_start_s = len(a) - xf  # where b (= nxt[b_skip:]) lands in the new output timeline
        y = _crossfade_join(a, b, xf)
        # carry nxt's grid into output time for the NEXT seam: nxt-time p -> output (b_out_start + p·SR − b_skip)
        y_ps = [(b_out_start_s + (p * SR - b_skip_s)) / SR for p in nxt_ps if p * SR >= b_skip_s - 1e-6]

    return _finalize(y, out_path)
