"""Best-parts: turn a finished mix into its ~180s highlight with a DJ-style arc.

THE VALIDATED RECIPE (sandbox-proven + founder ear-approved 2026-07-15):
  1. MIX the full song — the rich arrangement (done by render.py; UNCHANGED).
  2. CROP the finished mix to ~180s (the length that keeps ~75% of the rich moves;
     a full song's builds/breakdown/licks are scattered, and ~180s is the smallest
     window that still spans drop -> breakdown -> final lick. Under ~120s starves it).
  3. SNAP the crop edges to VOCAL-SILENT phrase boundaries so no lyric is ever chopped.
     Silence is measured on the OUTPUT VOCAL BUS — BOTH Song-2's placed vocals AND
     Song-1's contrast — reconstructed from the plan + the two vocal stems (not one
     raw stem, or a cut could land mid-word on the other singer).
  4. ARC each crop: a low->high BUILD at the start and a high->low WIND-DOWN at the end
     (the engine's own filter-build `_build_bed`, mirrored for the tail), so two crops
     chained together don't slam full-energy into full-energy — song 1 winds down while
     song 2 builds up, like a real DJ blend.
  5. CHAIN with the shipped beat-matched seam engine (set_render.assemble_beatmatched_set;
     UNCHANGED — the crop leaves a clean phrase grid, so the seam stays beat-aligned).

POST-RENDER ONLY. This never re-arranges and never edits render.py / validate.py — it
imports render.py's DSP helpers read-only and slices the already-rendered WAV. A summed
mix has no separable stems, so step 4 uses a filter build (the musical, stemless DJ ramp)
rather than a true drums-first stem build.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

# read-only reuse of the shipped render DSP (never modifies render.py)
from workers.render import _build_bed, _echo, _edge_fade, _vocal_take, _vocal_take_warped, SR

VSILENT = 0.15        # a bar with vocal energy under this is "vocal-silent" (Experiment 2 threshold)
TARGET_SECS = 180.0   # aim length of the highlight
BUILD_BARS = 8        # bars of build-in / wind-down at each edge (matches an 8-bar seam crossfade)
_ANTICLICK_MS = 10


def _winddown(seg: np.ndarray) -> np.ndarray:
    """Mirror of `_build_bed`: open+loud -> muffled+quiet (reverse in time, build, reverse back)."""
    return _build_bed(seg[::-1].copy(), SR)[::-1].copy()


def choose_window(phrases, silent, sung, target: float) -> tuple[float, float]:
    """Which ~`target`-second stretch of the finished mix to keep.

    THE RULE IT REPLACES, and why. It used to be "end just after the last sung phrase, start
    `target` earlier". On a normal-length beat everything fits inside that and it is right. On a
    long one it is not: the founder's Rapture x God's Plan mix (8 minutes, Drake at 1:04, 2:56 and
    7:28) ended at 7:28, reeled back three minutes, and threw the first two sections away - so the
    vocal arrived 2m40s into a 3m mix. Measured on the real render: 31s of singing kept, 36s binned.
    Four of the 25 menu beats are over five minutes, and SET members are hit identically (both
    routes call the same crop), so it is beat length, not singles-vs-sets.

    THE SMALLEST FIX THAT WORKS, deliberately (founder: change only the part that was pointed out).
    The old window is still computed FIRST and returned UNCHANGED whenever it already keeps all the
    singing - so every mix that sounds right today is byte-identical, and none of the ear-checked
    ones move. Only when it would throw singing away does this look for a better window.

    Both edges stay on silent phrase boundaries, so a lyric still can never be chopped in half.
    `sung` is (start, end) stretches where somebody is singing, on the OUTPUT bus - both singers.
    """
    silent_phrases = [p for p in phrases if silent(p)]
    if not silent_phrases:
        silent_phrases = list(phrases)

    def kept(s: float, e: float) -> float:
        return sum(max(0.0, min(b, e) - max(a, s)) for a, b in sung)

    # --- today's window, unchanged -------------------------------------------------------
    if sung:
        last_voc = max(b for _, b in sung)
        end_t = next((p for p in phrases if p > last_voc and silent(p)), phrases[-1])
    else:
        end_t = phrases[-1]
    earlier = [p for p in silent_phrases if p <= end_t - target]
    start_t = earlier[-1] if earlier else silent_phrases[0]

    total = sum(b - a for a, b in sung)
    if not sung or kept(start_t, end_t) >= total - 1e-6:
        return start_t, end_t          # nothing is being lost - leave it exactly as it was

    # --- it would lose singing: take the window that keeps the most -----------------------
    # Ties go to the LATEST window, which is the direction the old rule already leaned, so a mix
    # where several windows are equally good lands where it would have before.
    best = (start_t, end_t)
    best_kept = kept(start_t, end_t)
    for s in silent_phrases:
        ends = [p for p in silent_phrases if s < p <= s + target]
        if not ends:
            continue
        e = ends[-1]
        k = kept(s, e)
        if k > best_kept + 1e-6 or (abs(k - best_kept) <= 1e-6 and s > best[0]):
            best, best_kept = (s, e), k
    return best


def _placements(plan):
    if getattr(plan, "placements", None):
        return plan.placements
    return [type("P", (), {"anchor": plan.anchor, "vocal_src": plan.vocal_src, "warp": None, "echo": False})()]


def crop_and_arc(plan, mix_wav: Path, s2_vocal: Path, s1_vocal: Path | None, out_wav: Path,
                 target: float = TARGET_SECS, build_bars: int = BUILD_BARS) -> dict:
    """Crop a finished mix to its ~`target`s highlight with vocal-silent edges + build/wind-down arcs.

    `plan` — the MixPlan the mix was rendered from (needs out_downbeats/out_phrase_starts, i.e. a
             set-grid-attached plan). `s2_vocal` — Song 2's vocal stem; `s1_vocal` — Song 1's vocal
             stem (or None). Returns {"wav": out_wav, "phrase_starts": [secs in CROP time], "frames": int}.
    If the plan carries no output grid, returns the mix unchanged (safe no-op)."""
    full, _ = sf.read(str(mix_wav), dtype="float32", always_2d=True)
    out_db = np.asarray(plan.out_downbeats or [])
    phrases = list(plan.out_phrase_starts or [])
    if out_db.size < 2 or not phrases:            # no grid to crop against -> pass through unchanged
        sf.write(str(out_wav), full, SR, subtype="PCM_16")
        return {"wav": out_wav, "phrase_starts": phrases, "frames": len(full)}

    # 1. reconstruct the OUTPUT vocal bus (both sources) to find vocal-silence
    bus = np.zeros((len(full), 2), dtype=np.float32)
    def lay(sl, t):
        a = max(0, int(t * SR)); sl = sl[: max(0, len(bus) - a)]; bus[a:a + len(sl)] += sl
    for p in _placements(plan):
        warp = getattr(p, "warp", None)
        v = _edge_fade(_vocal_take_warped(s2_vocal, [list(w) for w in warp])) if warp else \
            _edge_fade(_vocal_take(s2_vocal, p.vocal_src[0], max(p.vocal_src[1] - p.vocal_src[0], 0.0), plan.vocal_stretch))
        if getattr(p, "echo", False):
            v = _echo(v, plan.master_bpm)
        lay(v, p.anchor)
    if s1_vocal is not None and Path(s1_vocal).exists():
        for s, e in getattr(plan, "s1_vocal_regions", []) or []:
            lay(_edge_fade(_vocal_take(s1_vocal, s, max(e - s, 0.0), 1.0)), s)

    # 2. per-output-bar vocal RMS -> normalized silence curve
    mono = bus.mean(axis=1)
    ve = []
    for i in range(len(out_db)):
        s = out_db[i]; e = out_db[i + 1] if i + 1 < len(out_db) else len(mono) / SR
        seg = mono[int(s * SR):int(e * SR)]
        ve.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    ve = np.asarray(ve); ve = ve / (ve.max() or 1.0)
    def bar_of(t): return max(0, min(int(np.searchsorted(out_db, t, side="right") - 1), len(ve) - 1))
    def silent(t): b = bar_of(t); return ve[b] < VSILENT and ve[max(0, b - 1)] < VSILENT

    # 3. vocal-silent edges: end just after the last sung phrase; start ~target earlier, on a silent boundary
    voiced = [i for i, v in enumerate(ve) if v >= VSILENT]
    if not voiced:                                 # instrumental-only mix -> nothing to protect; pass through
        sf.write(str(out_wav), full, SR, subtype="PCM_16")
        return {"wav": out_wav, "phrase_starts": phrases, "frames": len(full)}
    # The window is chosen by `choose_window`, which keeps today's "end just after the last sung
    # phrase" answer UNCHANGED whenever it already captures all the singing, and only looks for a
    # better one when it would throw some away (the 8-minute-beat case — see that function). The
    # fallbacks it needs are inside it: a short or vocal-dense mix may have no silent phrase at all.
    bar_secs = float(out_db[1] - out_db[0]) if len(out_db) > 1 else 0.0
    sung = [(float(out_db[i]), float(out_db[i]) + bar_secs) for i in voiced]
    start_t, end_t = choose_window(list(phrases), silent, sung, target)

    # 4. slice + arc (build-in / wind-down) + tiny anti-click
    bar = int((60.0 / plan.master_bpm) * 4 * SR)
    if int(end_t * SR) - int(start_t * SR) < 2 * bar:  # window too short to be a real highlight -> serve whole
        sf.write(str(out_wav), full, SR, subtype="PCM_16")
        return {"wav": out_wav, "phrase_starts": phrases, "frames": len(full)}
    seg = full[int(start_t * SR):int(end_t * SR)].copy()
    span = build_bars * bar
    if len(seg) > 2 * span:
        seg[:span] = _build_bed(seg[:span], SR)    # low -> high (muffled+quiet -> open+loud)
        seg[-span:] = _winddown(seg[-span:])       # high -> low (open+loud -> muffled+quiet)
    k = int(_ANTICLICK_MS / 1000 * SR)
    if len(seg) > 2 * k:
        seg[:k] *= np.linspace(0, 1, k)[:, None]; seg[-k:] *= np.linspace(1, 0, k)[:, None]

    sf.write(str(out_wav), seg, SR, subtype="PCM_16")
    crop_ps = [round(ps - start_t, 3) for ps in phrases if start_t <= ps <= end_t + 1e-6]
    return {"wav": out_wav, "phrase_starts": crop_ps, "frames": len(seg)}
