"""Audio-difference check for listening rounds — measured on the ISOLATED VOCAL, not the full mix.

WHY: full-mix waveform correlation is too blunt. The drums+bass bed dominates the waveform, so an
effect that clearly changes how the VOCAL is perceived (e.g. reverb) can read as "near-identical" on
the full mix — which wrongly killed a reverb listening round (2026-08-05). This compares the isolated
processed-vocal signals instead, and uses a log-magnitude SPECTRAL difference as the primary metric
(reverb changes the spectral tail more than the raw waveform shape).

Two signals of different length are compared over their OVERLAP (the shorter length), so a reverb tail
that only rings PAST the end (truncated-vs-ringing on a continuous vocal) is correctly identical over
the shared region — that bit-identical finding is real and must be preserved.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

# Calibrated so the two anchor cases separate cleanly (see scripts validation / test_audio_diff):
#   - truncated-vs-ringing on a continuous vocal  -> spectral_diff ~0 (IDENTICAL over the overlap)
#   - a subtle reverb the founder could hear       -> spectral_diff well above this (DISTINCT)
DISTINCT_SPECTRAL = 0.02


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim > 1 else x


def compare(a: np.ndarray, b: np.ndarray) -> dict:
    """Compare two isolated-vocal signals over their overlap. Returns waveform corr, rms-difference in
    dB, and the PRIMARY perceptual metric: mean log-magnitude spectral difference."""
    m = min(len(a), len(b))
    if m == 0:
        return {"corr": 1.0, "rms_diff_db": -99.0, "spectral_diff": 0.0, "overlap_secs": 0.0}
    a = _mono(a[:m]).astype(np.float64)
    b = _mono(b[:m]).astype(np.float64)
    denom = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    corr = float(np.sum(a * b) / denom) if denom > 0 else 1.0
    ra = float(np.sqrt(np.mean(a * a)))
    diff_rms = float(np.sqrt(np.mean((a - b) ** 2)))
    rms_diff_db = 20.0 * np.log10(diff_rms / ra) if ra > 0 and diff_rms > 0 else -99.0
    fa = np.abs(stft(a, nperseg=2048, noverlap=1536)[2])
    fb = np.abs(stft(b, nperseg=2048, noverlap=1536)[2])
    eps = 1e-8
    spectral_diff = float(np.mean(np.abs(np.log(fa + eps) - np.log(fb + eps))))
    return {"corr": corr, "rms_diff_db": rms_diff_db, "spectral_diff": spectral_diff,
            "overlap_secs": m / 44100.0}


def distinct(a: np.ndarray, b: np.ndarray, thresh: float = DISTINCT_SPECTRAL) -> bool:
    """True if the two isolated vocals are perceptibly different (spectral difference above `thresh`)."""
    return compare(a, b)["spectral_diff"] > thresh


def all_distinct(named: dict[str, np.ndarray], thresh: float = DISTINCT_SPECTRAL) -> list[tuple]:
    """Return the list of (name_a, name_b, spectral_diff) pairs that are NOT distinct — empty == every
    file measurably differs from every other. For guarding a listening set before delivery."""
    items = list(named.items())
    bad = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            c = compare(items[i][1], items[j][1])
            if c["spectral_diff"] <= thresh:
                bad.append((items[i][0], items[j][0], round(c["spectral_diff"], 4)))
    return bad
