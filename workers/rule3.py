"""Rule 3 — CHOP & REPEAT — the RENDERER (engine). Executes a `Rule3Plan` into a WAV.

Deliberately a SEPARATE module that REUSES the shared DSP primitives already living in
`workers/render.py` (beat-locked per-bar warp, the Rule-4 echo, the reverb, stem summing) rather
than editing that guarded file. The BPM+key foundation is applied UPSTREAM (the caller passes the
already-tempo/key-matched vocal + the beat's downbeats); this module only lays the chops down,
beat-locked, word-safe, echoed, trading in the beat's gaps.

(Future cleanup: extract the shared `_vocal_take*/_echo/_reverb/_sum_stems` primitives into a
neutral `workers/_dsp.py` so neither Rule 3 nor Rule 4 imports the other's private names. That
refactor touches the guarded render.py, so it waits for the careful path.)
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import soundfile as sf

from app.planner.rule3 import Rule3Plan, unit_bars
from workers import render

SR = render.SR
# Balance (founder decision 2026-08-07: BEAT FULL + VOCAL SUBTLE on Chop & Echo, not Simple).
# The beat stays up front (only a light duck under a chop) and the chop sits UNDER it; reverb bumped a
# little so the chop shares the beat's space, echo kept. Ear-tunable — the founder confirms in the app.
_WET = 0.55          # reverb wet on the chop tail (was 0.40 — more space so the vocal glues in)
_CHOP_GAIN = 0.90    # chop level over the bed (was 1.10 — vocal SUBTLE, sits under the beat)
_DUCK = 10 ** (-1.0 / 20)   # duck the bed only ~1 dB under a chop (was ~3 dB) — BEAT STAYS FULL


def envelope(path: Path, hop_ms: float = 10.0) -> tuple[np.ndarray, float]:
    """A framed RMS envelope of a mono-summed audio file, for the planner's phrase/gap detection.
    Returns (env, samples_per_second_of_env). ~100 Hz env (10 ms hop)."""
    y = render._decode(Path(path)).mean(axis=1)
    hop = max(1, int(SR * hop_ms / 1000))
    n = len(y) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32), SR / hop
    fr = y[: n * hop].reshape(n, hop)
    env = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1) + 1e-12).astype(np.float32)
    return env, SR / hop


def _tail_fade(t: np.ndarray) -> np.ndarray:
    """Hold ~40 %, then cosine-fade to zero — the last word is heard, then eases out (never a cut)."""
    k = len(t)
    if not k:
        return t
    h = int(0.4 * k)
    f = np.ones(k, dtype=np.float32)
    f[h:] = np.cos(np.linspace(0, np.pi / 2, k - h))
    return t * f[:, None]


def _make_unit(unit, didx: int, downbeats: list[float], voc: str) -> np.ndarray:
    """Render one chop unit beat-locked at beat-downbeat `didx`: each phrase's bars are warped to the
    beat's bars, and each phrase's last word finishes past its bar line and fades (word-safe)."""
    parts, pos, cur = [], 0, didx
    for blk in unit:
        bars = blk.bars
        warp = [(s0, s1, downbeats[cur + i + 1] - downbeats[cur + i]) for i, (s0, s1) in enumerate(bars)]
        body = render._vocal_take_warped(voc, warp)
        last = bars[-1]
        ratio = (last[1] - last[0]) / (downbeats[cur + len(bars)] - downbeats[cur + len(bars) - 1])
        parts.append((pos, body))
        tail_dur = blk.word_end - last[1]
        if tail_dur > 0.05:                       # the last word rings past the bar -> finish + fade
            tail = _tail_fade(render._vocal_take(voc, last[1], tail_dur, ratio))
            parts.append((pos + len(body), tail))
        pos += len(body)
        cur += len(bars)
    total = max(p + len(s) for p, s in parts)
    c = np.zeros((total, 2), dtype=np.float32)
    for p, s in parts:
        b = min(total, p + len(s))
        c[p:b] += s[:b - p]
    k = int(SR * 0.008)
    c[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
    return c


def _wetten(clip: np.ndarray, bpm: float) -> np.ndarray:
    """The Rule-4 echo + reverb tail on a chop (reused engine functions), padded so the reverb rings."""
    pad = np.zeros((int(render._REVERB_SECS * SR), 2), dtype=np.float32)
    return render._reverb(np.vstack([render._echo(clip, bpm), pad]), _WET, SR)


def render_rule3(plan: Rule3Plan, downbeats: list[float], bpm: float,
                 song1_stems: Mapping[str, Path], song1_wav: Path,
                 song2_vocal: Path, out_path: Path) -> Path:
    """Render the chop-and-repeat mix. `song2_vocal` is already tempo/key-matched (foundation upstream).
    keep_beat_vocal → the beat's full track is the bed (chops trade in its gaps); else its stems only."""
    voc = str(song2_vocal)
    if plan.keep_beat_vocal:
        bed = render._decode(Path(song1_wav)).astype(np.float32)
    else:
        bed = render._sum_stems([Path(song1_stems[s]) for s in ("drums", "bass", "other")]).astype(np.float32)
    n = len(bed)
    units = {"A": plan.a_unit, "C": plan.c_unit}

    bed_gain = np.ones(n, dtype=np.float32)
    adds: list[tuple[int, np.ndarray]] = []
    for hit in plan.hits:
        unit = units[hit.block]
        didx = hit.beat_db_index
        if didx < 0 or didx + unit_bars(unit) + 1 >= len(downbeats):
            continue                                        # not enough grid room — skip (never crash)
        clip = _wetten(_make_unit(unit, didx, downbeats, voc), bpm)
        at = int(downbeats[didx] * SR)
        b = min(n, at + len(clip))
        if b <= at:
            continue
        bed_gain[at:b] = np.minimum(bed_gain[at:b], _DUCK)
        adds.append((at, clip))

    canvas = bed * bed_gain[:, None]
    for at, clip in adds:
        b = min(n, at + len(clip))
        canvas[at:b] += _CHOP_GAIN * clip[: b - at]

    peak = float(np.max(np.abs(canvas))) if canvas.size else 0.0
    y = np.clip(canvas * (0.89 / max(peak, 1e-6)), -1.0, 1.0).astype(np.float32)
    sf.write(str(out_path), y, SR)
    return out_path
