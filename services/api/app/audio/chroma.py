"""Chromagram + rotation detection (pure numpy). Used by the referee (validate.py) to INDEPENDENTLY
confirm a key-shifted vocal actually rotated by the claimed semitones — consistency (two engine runs
agreeing) is not correctness. Measure over the WHOLE stem: short/flat slices read unreliably."""
from __future__ import annotations

import numpy as np


def chroma(y: np.ndarray, sr: int, n_fft: int = 4096, hop: int = 2048) -> np.ndarray:
    """Average 12-bin pitch-class energy across the signal (simple FFT chromagram), L1-normalized."""
    y = np.asarray(y, dtype=np.float64)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    pc = np.full(len(freqs), -1, dtype=int)
    nz = freqs > 20
    midi = 69 + 12 * np.log2(np.where(nz, freqs, 440.0) / 440.0)
    pc[nz] = np.round(midi[nz]).astype(int) % 12
    idx = [np.where(pc == k)[0] for k in range(12)]
    C = np.zeros(12)
    for i in range(0, max(1, len(y) - n_fft), hop):
        mag = np.abs(np.fft.rfft(y[i:i + n_fft] * win))
        for k in range(12):
            C[k] += mag[idx[k]].sum()
    total = C.sum()
    return C / total if total > 0 else C


def best_rotation(orig: np.ndarray, shifted: np.ndarray) -> tuple[int, float, list[float]]:
    """Return (rotation 0..11, confidence margin, corrs). A vocal shifted UP by s semitones has a
    chroma that is `orig` rolled by s, so best rotation == s % 12. `margin` = best corr minus 2nd-best
    corr (how unambiguous the reading is — near 0 means the material is too chroma-flat to judge).
    `corrs[r]` is the correlation at each rotation r, so a caller can ask "is the CLAIMED rotation
    competitive?" rather than only "which rotation is best?"."""
    o = orig - orig.mean()
    sh = shifted - shifted.mean()
    corrs = []
    for r in range(12):
        rolled = np.roll(o, r)
        d = np.linalg.norm(rolled) * np.linalg.norm(sh) + 1e-12
        corrs.append(float(np.dot(rolled, sh) / d))
    order = np.argsort(corrs)[::-1]
    return int(order[0]), float(corrs[order[0]] - corrs[order[1]]), corrs
