"""Chromagram + rotation detection (pure numpy). Used by the referee (validate.py) to INDEPENDENTLY
confirm a key-shifted vocal actually rotated by the claimed semitones — consistency (two engine runs
agreeing) is not correctness. Measure over the WHOLE stem: short/flat slices read unreliably."""
from __future__ import annotations

from pathlib import Path

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


# --- Empirical key-matching (AutoMashUpper — Davies, Hamel, Yoshii & Goto, ISMIR 2013) ------------
# The detected KEY LABEL is a hypothesis; on real uploads it is often wrong or flagged. When
# keys.resolve_key_shift refuses to trust the labels, we choose the vocal pitch-shift by MEASURING
# harmonic fit instead: rotate the vocal's chroma over every candidate semitone shift and pick the one
# whose cosine similarity to the beat's harmony (AutoMashUpper's H_n) is highest, ties broken toward
# the SMALLEST shift (least pitch move = least artefact — the "closest to native" preference). The
# chosen shift is applied formant-preserved (app.audio.pitch), so the voice keeps its natural size.
# cap defaults to 3 = the ±3-semitone formant-preserved ceiling (founder decision 2026-08-07; the
# fuzzy-keymixing rule is ±2, extendable to ±3 with formant correction). REUSES `chroma()` above so
# the referee and the matcher read pitch-classes the same way (never two chroma implementations).
_PC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def rank_shifts(beat_chroma: np.ndarray, voc_chroma: np.ndarray, cap: int = 3) -> list[tuple[int, float]]:
    """Score every semitone shift s in [-cap, cap] by cosine similarity of the vocal chroma rotated UP
    by s against the beat chroma (AutoMashUpper H). Best-first, ties toward smaller |s|. Pure numpy —
    unit-testable with no audio."""
    b = np.asarray(beat_chroma, dtype=np.float64)
    v = np.asarray(voc_chroma, dtype=np.float64)
    bn = b / (np.linalg.norm(b) + 1e-12)
    scored: list[tuple[int, float]] = []
    for s in range(-cap, cap + 1):
        vr = np.roll(v, s)                                   # rotate vocal UP by s semitones
        vn = vr / (np.linalg.norm(vr) + 1e-12)
        scored.append((s, float(np.dot(vn, bn))))
    scored.sort(key=lambda sc: (-round(sc[1], 6), abs(sc[0])))
    return scored


def best_shift(beat_chroma: np.ndarray, voc_chroma: np.ndarray, cap: int = 3) -> tuple[int, float, float]:
    """The winning shift as (shift, score, baseline_score); baseline is the no-shift (s=0) cosine, so
    the caller can see how much the shift improved harmonic fit. Pure."""
    ranked = rank_shifts(beat_chroma, voc_chroma, cap)
    baseline = next(c for s, c in ranked if s == 0)
    shift, score = ranked[0]
    return shift, score, baseline


def _decoded_chroma(paths: list[Path], t0: float | None = None, t1: float | None = None) -> np.ndarray:
    """Chroma of the summed audio of `paths` (optionally the [t0,t1]s window), via the shared `chroma()`.
    Imports the decoder lazily to avoid an import cycle with the workers package."""
    from workers.render import SR, _decode

    y: np.ndarray | None = None
    for p in paths:
        d = _decode(Path(p)).mean(axis=1)
        if y is None:
            y = d
        else:
            n = min(len(y), len(d))
            y = y[:n] + d[:n]
    if y is None or not len(y):
        return np.ones(12, dtype=np.float64) / 12.0
    if t0 is not None:
        y = y[int(t0 * SR): int((t1 if t1 is not None else len(y) / SR) * SR)]
    if not len(y):
        return np.ones(12, dtype=np.float64) / 12.0
    return chroma(y, SR)


def empirical_shift(beat_harmony_paths: list[Path], vocal_path: Path, cap: int = 3,
                    vocal_region: tuple[float, float] | None = None) -> tuple[int, float, float]:
    """Measure the best vocal pitch-shift for this pair from AUDIO. `beat_harmony_paths` = the beat
    song's harmonic stems (bass + other); `vocal_path` = the vocal stem; `vocal_region` limits the
    vocal to its sung stretch. Returns (shift, score, baseline). NEVER declines — always returns the
    best available shift within ±cap (founder rule: no pair is ever un-mixable)."""
    beat = _decoded_chroma([Path(p) for p in beat_harmony_paths])
    t0, t1 = (vocal_region or (None, None))
    voc = _decoded_chroma([Path(vocal_path)], t0, t1)
    return best_shift(beat, voc, cap)
