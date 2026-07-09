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

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100  # everything renders at CD rate, stereo
_TARGET_PEAK = 10 ** (-1.0 / 20)  # -1 dBFS headroom
_CEILING = 0.999  # brickwall safety — must stay below the validator's clip ceiling


class SetRenderError(Exception):
    """Raised when the set-assembly engine cannot produce a set."""


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

    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.0:
        y = y * (_TARGET_PEAK / peak)
    np.clip(y, -_CEILING, _CEILING, out=y)

    sf.write(out_path, y, SR, subtype="PCM_16")
    return out_path
