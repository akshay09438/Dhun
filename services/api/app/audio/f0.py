"""Voice-pitch (f0) measurement — the reliable ruler for "did the pitch shift land?".

Chroma rotation (audio/chroma.py) fingerprints WHICH NOTES are present across a whole stem. That
works on clean melodic singing but fails on speech-like vocals (rap/whisper — e.g. Bad Guy, Panda):
their broadband, un-pitched content dominates the fingerprint and does NOT move under a pitch
shift, so a correctly shifted vocal still reads "rotation 0" and gets wrongly declined (diagnosed
2026-08-10: engine output measured +1.91/-0.99/-1.00 st by this method vs chroma reading 0/0/8).

This module instead tracks the singer's actual fundamental frequency (autocorrelation per frame),
compares original vs shifted ONLY on frames where BOTH are confidently voiced, and reports the
median shift in semitones. It is pure measurement — no audio is modified.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

# Analysis window: the middle of the stem (densest singing), capped so a long song stays fast.
_MAX_SECONDS = 150.0
_FMIN, _FMAX = 70.0, 1000.0    # singable f0 range. The ceiling is deliberately ABOVE the top of the
#                                sung range (~C6) plus a +2 st shift: at 500 Hz a high female belt /
#                                falsetto shifted UP fell out of range, the tracker locked a subharmonic,
#                                and a CORRECT shift measured as ~-10 st. (Adversarial review NEW-1.)
_FRAME, _HOP = 2048, 1024
_VOICED_CONF = 0.5             # normalized autocorr peak below this = unvoiced frame
_RMS_FLOOR = 0.25              # frame quieter than this x stem RMS = silence, skipped
_OCTAVE_GUARD_ST = 6.0         # per-frame deltas beyond this are octave errors, discarded
MIN_VOICED_FRAMES = 30         # fewer paired voiced frames than this => "can't measure"



def _load_mono_mid(path: Path, max_seconds: float = _MAX_SECONDS) -> tuple[np.ndarray, int]:
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    limit = int(max_seconds * sr)
    if len(y) > limit:
        mid = len(y) // 2
        y = y[mid - limit // 2 : mid + limit // 2]
    return y, sr


def _f0_frames(y: np.ndarray, sr: int) -> np.ndarray:
    """Per-frame f0 in Hz (NaN where unvoiced/quiet), via normalized autocorrelation + parabolic
    refinement. Deliberately simple and dependency-free (pure numpy) — proven on real stems."""
    lo, hi = int(sr / _FMAX), int(sr / _FMIN)
    rms_all = float(np.sqrt(np.mean(y**2))) + 1e-12
    out: list[float] = []
    for s in range(0, len(y) - _FRAME, _HOP):
        w = y[s : s + _FRAME]
        if float(np.sqrt(np.mean(w**2))) < _RMS_FLOOR * rms_all:
            out.append(np.nan)
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, "full")[_FRAME - 1 :]
        if ac[0] <= 0:
            out.append(np.nan)
            continue
        ac = ac / ac[0]
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] < _VOICED_CONF:
            out.append(np.nan)
            continue
        lag = float(lo + k)
        if 0 < k < len(seg) - 1:  # parabolic peak refinement
            a, b, c = seg[k - 1], seg[k], seg[k + 1]
            den = a - 2 * b + c
            if abs(den) > 1e-12:
                lag += 0.5 * (a - c) / den
        out.append(sr / lag)
    return np.asarray(out)


def measured_shift_semitones(original: Path, shifted: Path) -> tuple[float, int] | None:
    """Median pitch shift (semitones) from `original` to `shifted`, measured on frames where BOTH
    are confidently voiced. Returns (semitones, n_frames), or None when there are too few voiced
    frames to measure (caller falls back to its other evidence). Never raises on unreadable
    audio — unreadable == unmeasurable == None."""
    try:
        yo, sr_o = _load_mono_mid(original)
        ys, sr_s = _load_mono_mid(shifted)
    except Exception:  # noqa: BLE001 — a measurement must never crash the caller
        return None
    n = min(len(yo), len(ys))
    if n < _FRAME * 2:
        return None
    fo = _f0_frames(yo[:n], sr_o)
    fs = _f0_frames(ys[:n], sr_s)
    m = min(len(fo), len(fs))
    fo, fs = fo[:m], fs[:m]
    ok = ~np.isnan(fo) & ~np.isnan(fs)
    if int(ok.sum()) < MIN_VOICED_FRAMES:
        return None
    raw = 12.0 * np.log2(fs[ok] / fo[ok])
    semis = raw[np.abs(raw) < _OCTAVE_GUARD_ST]
    if len(semis) < MIN_VOICED_FRAMES:
        # The octave guard discards per-frame OUTLIERS. If it discarded essentially EVERYTHING while
        # plenty of paired voiced frames existed, the shift itself is huge/octave-wrong (e.g. a +14 st
        # render claimed as +2) — damning evidence, not "unmeasurable". Report the raw median so the
        # referee DECLINES, rather than returning None into the mod-12-blind chroma check which would
        # let an octave-wrong render pass. Safe because _FMAX now sits above the sung range + a +2 st
        # shift, so a CORRECT small shift is never discarded en masse. (Adversarial review, 2026-08-10.)
        return float(np.median(raw)), int(ok.sum())
    return float(np.median(semis)), int(len(semis))
