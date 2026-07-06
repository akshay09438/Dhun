"""Render the arrangement's VOCAL layer onto silence — the "arranged-vocal bus".

The live player (browser) plays Song 1's stems at steady gain and needs Song 2's
arranged vocal as a separate, sync-playable track it can mute/unmute on the beat.
Rather than re-implement the warp/fade/contrast math in JS, this reuses the trusted
render engine's helpers to bake exactly the vocal half of `render_mix` onto a silent
buffer: same placements, same per-bar beat-lock, same edge fades, plus Song 1's own
contrast vocal. It deliberately skips the bed sum, the master peak-normalize, and the
bed-only effects (sweep, beat-breath) — those live only in the finished Download.

Level: the vocal is added at ratio 1.0 (identical to `render_mix`), and the bus is NOT
peak-normalized, because the browser sums it live with the raw stems — so the relative
balance between vocal and bed matches the Download (whose global normalize is uniform).
Only a safety clip is applied so a pathological overlap can't exceed the WAV's range.
This module imports render.py's helpers; it never modifies the engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import soundfile as sf

from workers.render import (  # reuse the single source of truth for vocal placement
    SR,
    RenderError,
    _CEILING,
    _decode,
    _edge_fade,
    _placements_of,
    _vocal_take,
    _vocal_take_warped,
)


def _hold(buf: np.ndarray, need: int) -> np.ndarray:
    """Extend the buffer with silence so it can hold audio out to `need` samples."""
    if need > len(buf):
        return np.vstack([buf, np.zeros((need - len(buf), 2), dtype=np.float32)])
    return buf


def render_full_vocal(song2_vocal: Path, stretch: float, out_path: Path) -> Path:
    """Song 2's WHOLE vocal, tempo-matched to Song 1 (one global stretch), from t=0 — a
    CONTINUOUS vocal the live player can bring in/out anywhere, for as long as Song 2 sings.

    This is the live 'Vocals' part: unlike the sparse arranged bus (`render_vocal_bus`, used
    for the Download's arc), it plays Song 2's vocal continuously so 'bring the vocal in' works
    at any moment. It's a steerable approximation — a single global atempo (not the per-bar
    beat-lock), which the founder accepted for live steering; the Download keeps the locked arc.
    Level is ratio 1.0 (sits with the raw stems, like the arranged bus); only a safety clip.
    """
    dur = len(_decode(song2_vocal)) / SR  # the vocal's own length, before stretch
    voc = _edge_fade(_vocal_take(song2_vocal, 0.0, dur, stretch)) if dur > 0 else np.zeros((0, 2), np.float32)
    np.clip(voc, -_CEILING, _CEILING, out=voc)
    if len(voc) == 0:
        voc = np.zeros((1, 2), dtype=np.float32)
    sf.write(out_path, voc, SR, subtype="PCM_16")
    return out_path


def render_vocal_bus(plan, song1_stems: Mapping[str, Path], song2_vocal: Path,
                     out_path: Path) -> Path:
    """Render `plan`'s vocal layer (Song 2 placed + Song 1 contrast) onto silence."""
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")

    layer = np.zeros((0, 2), dtype=np.float32)

    for p in _placements_of(plan):
        warp = getattr(p, "warp", None)
        if warp:  # per-bar beat-lock (M4d) — each bar re-locked to Song 1's grid
            voc = _edge_fade(_vocal_take_warped(song2_vocal, warp))
        else:  # legacy single global stretch (M3/M4a–c cached plans)
            start, end = p.vocal_src
            voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        anchor = max(0, int(p.anchor * SR))
        need = anchor + len(voc)
        layer = _hold(layer, need)
        layer[anchor:need] += voc

    # Song 1's own vocal answering in the gaps (contrast) — same as render_mix, no stretch.
    s1_vocals = song1_stems.get("vocals")
    for s, e in getattr(plan, "s1_vocal_regions", []):
        if s1_vocals is None:
            break
        take = _edge_fade(_vocal_take(s1_vocals, s, max(e - s, 0.0), 1.0))
        a0 = max(0, int(s * SR))
        layer = _hold(layer, a0 + len(take))
        layer[a0:a0 + len(take)] += take

    np.clip(layer, -_CEILING, _CEILING, out=layer)  # safety only — NOT a peak-normalize
    if len(layer) == 0:
        layer = np.zeros((1, 2), dtype=np.float32)  # a valid (silent) WAV even with no vocal
    sf.write(out_path, layer, SR, subtype="PCM_16")
    return out_path
