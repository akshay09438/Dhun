"""Phrase-throw SELECTION (planner side — NOT a dangerous surface). Decides WHERE echo throws fire and
WHICH cut ratio each uses, from Song 1's RELIABLE structural sensors (downbeats + energy_curve) — never
vocal_regions (unreliable on blob tracks). The engine (render.py) later EXECUTES these decisions; this
module only PLANS them, so it can be inspected and tuned before a single sample is rendered.

Throws are PUNCTUATION, not grammar: the vocal sings normally, and ~THROW_RATE of the 4-bar moments fire
a throw (a sing/carry echo event), then return to normal. Deterministic — same (songs, prompt, take) →
same decisions (seed passed in), so the content-addressed mix cache holds and Regenerate is reproducible.
"""
from __future__ import annotations

import random

from app.planner.fence import placement_end

# ==================================== TASTE PARAMETERS — TUNE BY EAR ====================================
# These are TASTE, not logic. They will move after the first listen. Keep them HERE, together — never
# scatter them into the code below.
THROW_RATE = 0.25          # fraction of 4-bar moments that fire a throw (punctuation, not grammar)
MOMENT_BARS = 4            # granularity: a "moment" is a 4-bar half-phrase (8-bar gave only 1-2 throws/mix)
MIN_THROW_SPACING = 1      # at least this many non-throw moments between two throws (spread, no clustering)
HIGH_ENERGY_PCTL = 0.60    # a moment at/above this energy rank WITHIN its placement counts as "high energy"
COMEDOWN_DROP = 0.85       # a "come-down" needs a REAL drop: next moment below this fraction of this one
                           # (a tiny dip like 0.99→0.96 is NOT a come-down — that made every ratio identical)
# energy → ratio (sing_bars, carry_bars): "tight on high energy, long carries into come-downs."
RATIOS_COMEDOWN = [(2, 6), (1, 3)]   # energy dropping → long carry, the echo fills the come-down
RATIOS_HIGH     = [(6, 2), (2, 2)]   # high energy     → brief / tight throw, the vocal stays forward
RATIOS_MID      = [(4, 4)]           # steady          → balanced
RATIOS_SHORT    = [(2, 2), (1, 3)]   # 4-bar fallbacks when a moment is too short for the chosen ratio
# =======================================================================================================


def _nearest_downbeat_index(downbeats: list, t: float) -> int:
    return min(range(len(downbeats)), key=lambda i: abs(downbeats[i] - t)) if downbeats else 0


def _mean_energy(energy: list, lo: int, n: int) -> float:
    window = energy[lo:lo + n]
    return sum(window) / len(window) if window else 0.0


def plan_throws(placements: list, a1, master_bpm: float, vocal_stretch: float, seed: int) -> list[dict]:
    """Per-placement throw decisions. For each placement returns its 4-bar moments and, per moment,
    whether it throws, which ratio, and WHY (energy that drove it) — the fields the inspectable dump and
    the engine both read. Pure arithmetic; deterministic given `seed`."""
    rng = random.Random(seed)
    bar_secs = (60.0 / master_bpm) * 4.0 if master_bpm else 2.0
    downbeats = list(getattr(a1, "downbeats", []) or [])
    energy = list(getattr(a1, "energy_curve", []) or [])

    # ---- PASS 1: enumerate every placement's 4-bar moments (energy + come-down) ----
    per: list[dict] = []
    for pi, p in enumerate(placements):
        anchor = p.anchor
        end = placement_end(anchor, p.vocal_src, vocal_stretch, getattr(p, "warp", None))
        length_bars = max(0, round((end - anchor) / bar_secs))
        n_moments = length_bars // MOMENT_BARS
        i0 = _nearest_downbeat_index(downbeats, anchor)
        moments = []
        for j in range(n_moments):
            lo = i0 + j * MOMENT_BARS
            e = _mean_energy(energy, lo, MOMENT_BARS)
            e_next = _mean_energy(energy, lo + MOMENT_BARS, MOMENT_BARS) if j + 1 < n_moments else e
            moments.append({"j": j, "bar_lo": j * MOMENT_BARS, "energy": round(e, 3),
                            "comedown": e_next < e * COMEDOWN_DROP})
        # "high energy" threshold WITHIN this placement (relative to its own energy scale)
        es = sorted(m["energy"] for m in moments)
        hi = es[int(HIGH_ENERGY_PCTL * (len(es) - 1))] if es else 1.0
        per.append({"pi": pi, "anchor": anchor, "length_bars": length_bars,
                    "n_moments": n_moments, "moments": moments, "hi": hi})

    # ---- WEIGHT BY PLACEMENT LENGTH. A per-placement round(THROW_RATE * n) FLATTENS a 22-bar and a
    # 12-bar placement to one throw each (round(1.25)==round(0.75)==1), so long stretches go too long
    # with nothing happening. Instead pool ONE budget (THROW_RATE of ALL moments, so the overall rate
    # stays in band) and hand throws to the LONGEST placements first — long placements get proportionally
    # more; a short one may get none (it still carries the reverb bed). ----
    n_moms = [d["n_moments"] for d in per]
    budget = round(THROW_RATE * sum(n_moms))
    caps = [(nm + 1) // 2 for nm in n_moms]  # most throws that fit given MIN_THROW_SPACING
    target = [min(int(THROW_RATE * nm), caps[i]) for i, nm in enumerate(n_moms)]  # fair floor first
    remaining = budget - sum(target)
    while remaining > 0:
        elig = [i for i in range(len(per)) if target[i] < caps[i]]
        if not elig:
            break
        idx = max(elig, key=lambda i: (n_moms[i], -i))  # longest placement first (deterministic tiebreak)
        target[idx] += 1
        remaining -= 1

    # ---- PASS 2: within each placement pick `target` moments (come-down bias + spacing) + ratios ----
    result: list[dict] = []
    for d in per:
        moments, length_bars, hi = d["moments"], d["length_bars"], d["hi"]
        # come-downs preferred (a throw sits well going into a dip), then a SEEDED SPREAD across the rest
        # — NOT loudest-first, so throws land on steady mid-energy moments too (that is 4:4's only home).
        ranked = sorted(moments, key=lambda m: (not m["comedown"], rng.random()))
        chosen_js: list[int] = []
        for m in ranked:
            if len(chosen_js) >= target[d["pi"]]:
                break
            if all(abs(m["j"] - c) > MIN_THROW_SPACING for c in chosen_js):
                chosen_js.append(m["j"])
        chosen = set(chosen_js)
        for m in moments:
            if m["j"] not in chosen:
                m.update(chosen=False, ratio=None, reason="sings normally")
                continue
            avail = length_bars - m["bar_lo"]  # bars left from this moment to the placement end
            if m["comedown"]:
                cands, why = list(RATIOS_COMEDOWN), f"come-down (e={m['energy']}) → long carry"
            elif m["energy"] >= hi:
                cands, why = list(RATIOS_HIGH), f"high energy (e={m['energy']}) → tight throw"
            else:
                cands, why = list(RATIOS_MID), f"steady (e={m['energy']}) → balanced"
            rng.shuffle(cands)
            # length gate + fallback: the chosen ratio's cycle must fit; else a 4-bar short cycle; else none
            ratio = next((r for r in cands + RATIOS_SHORT if r[0] + r[1] <= avail), None)
            if ratio is None:
                m.update(chosen=False, ratio=None, reason=f"too short ({avail} bars left) → continuous")
            else:
                m.update(chosen=True, ratio=ratio, reason=f"{why} = {ratio[0]}:{ratio[1]}")
        result.append({"placement": d["pi"], "anchor": round(d["anchor"], 1),
                       "length_bars": length_bars, "n_moments": d["n_moments"], "moments": moments})
    return result
