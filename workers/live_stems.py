"""Render the arrangement's VOCAL layer onto silence — the "arranged-vocal bus".

The live player (browser) plays Song 1's stems at steady gain and needs Song 2's
arranged vocal as a separate, sync-playable track it can mute/unmute on the beat.
Rather than re-implement the warp/fade/contrast/chain math in JS, this reuses the trusted
render engine's helpers to bake exactly the vocal half of `render_mix` onto a silent
buffer: same placements, same per-bar beat-lock, same edge fades, the SAME per-placement
vocal chain (Phase-0 stages 1-8: de-ess, highpass, compress, saturate, presence, reverb)
and the same chop/echo, plus Song 1's own contrast vocal. It deliberately skips the bed sum,
the master peak-normalize, and the BED-side effects (sweep, beat-breath, and the stage-9
sidechain duck) — those act on the bed, which the browser plays as separate live stems, so
they live only in the finished Download. Net: the bus vocal is byte-identical to Export's.

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

from workers import chain_guards  # P2 peak-gain + crest mush guard, identical to render_mix
from workers.render import (  # reuse the single source of truth for vocal placement + chain
    SR,
    RenderError,
    _CEILING,
    _apply_vocal_chain,
    _chop_pattern,
    _echo,
    _edge_fade,
    _hold,
    _placements_of,
    _vocal_take,
    _vocal_take_warped,
)


def render_vocal_bus(plan, song1_stems: Mapping[str, Path], song2_vocal: Path,
                     out_path: Path) -> Path:
    """Render `plan`'s vocal layer (Song 2 placed + Song 1 contrast) onto silence."""
    if plan.master_bpm <= 0:
        raise RenderError("plan has a non-positive tempo")

    layer = np.zeros((0, 2), dtype=np.float32)

    # Phase-0 parity with Export (render_mix Pass 1): apply the SAME per-placement vocal chain here, so
    # the Play/steer preview carries the tuned vocal instead of a dry one. No vocal_moves (chain off, or
    # an old cached plan) -> vm is None -> this is a no-op and the bus is byte-identical to before. The
    # chain is vocal-only + length-preserving; the bed-side stage-9 duck is intentionally NOT here (the
    # live player mixes the bed as separate stems). placement_id is positional ("p{i}"), as the planner emits.
    bar = int((60.0 / plan.master_bpm) * 4 * SR)
    vmoves = {getattr(m, "placement_id", None): m for m in getattr(plan, "vocal_moves", []) or []}

    for i, p in enumerate(_placements_of(plan)):
        warp = getattr(p, "warp", None)
        if warp:  # per-bar beat-lock (M4d) — each bar re-locked to Song 1's grid
            voc = _edge_fade(_vocal_take_warped(song2_vocal, warp))
        else:  # legacy single global stretch (M3/M4a–c cached plans)
            start, end = p.vocal_src
            voc = _edge_fade(_vocal_take(song2_vocal, start, max(end - start, 0.0), plan.vocal_stretch))
        vm = vmoves.get(f"p{i}")
        if vm is not None:  # stages 1-8 — the identical call render_mix makes; no move -> skipped
            before = voc
            voc = _apply_vocal_chain(voc, vm, SR)
            bad = chain_guards.check_vocal_chain_output(before, voc)  # P2 peak-gain + crest mush guard
            if bad is not None:
                raise RenderError(bad)
        if getattr(p, "chop", False):  # Step 4 vocal chop over the entry's first bar
            k = min(bar, len(voc))
            if k > 0:
                voc[:k] = _chop_pattern(voc[:k], k, plan.master_bpm)
        if getattr(p, "echo", False):  # echo throw ringing into the drop
            voc = _echo(voc, plan.master_bpm)
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
