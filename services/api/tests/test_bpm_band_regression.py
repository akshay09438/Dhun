"""Regression guard for Change ① — the BPM safe-stretch band widening (±11% -> ±15%).

fence.SAFE_STRETCH_LO/HI moved 0.89/1.11 -> 0.85/1.15 (founder ear-approved, 2026-08-06), and
workers/set_render.py now IMPORTS those constants from fence instead of hardcoding them. This file
locks the two properties that make that change SAFE:

  1. MONOTONICITY — the widening only ADDS mixable pairs; it never silently turns a pair that used to
     mix into a decline. (No pair "reshuffles the wrong way".)
  2. CATALOG EDGE PAIRS — for the real catalog's near-old-edge pairs, none flip mixable->declined
     (only declined->mixable is allowed). Skips gracefully if the analysis files aren't present.
  3. SINGLE SOURCE OF TRUTH — set_render's band IS fence's band, the same imported object, so a future
     retune of fence propagates to the set engine automatically.

Pure arithmetic over fence.tempo_plan (the tempo gate the band controls) — no audio, no network.
"""

import json
import sys
from pathlib import Path

import pytest

from app.planner import fence

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import set_render  # noqa: E402

# The OLD band, before Change ①. tempo_plan's SAFE_STRETCH check is fully parameterised by lo/hi and
# the house-move caps did NOT change, so passing the old edges reproduces the exact pre-widen decision.
OLD_LO, OLD_HI = 0.89, 1.11


def _mixable(beat: float, vocal: float, lo: float, hi: float) -> bool:
    """The tempo gate the band governs: does this (beat, vocal) pair pass the safe-stretch band?"""
    return fence.tempo_plan(beat, vocal, lo=lo, hi=hi)[3] is True


# ---------------------------------------------------------------- 1. MONOTONICITY (the key property)


def test_widening_never_removes_a_mixable_pair():
    """Every (beat, vocal) pair mixable at the OLD ±11% band must STILL be mixable at the new default
    ±15% band. Widening the safe band can only ADD mixable pairs — never drop one — so no pair that a
    user could blend yesterday silently declines today. Swept across a dense BPM grid."""
    grid = [float(b) for b in range(80, 162, 2)]  # 80..160 step 2, both axes
    removed: list[tuple[float, float]] = []
    old_mixable = 0
    for beat in grid:
        for vocal in grid:
            if _mixable(beat, vocal, OLD_LO, OLD_HI):
                old_mixable += 1
                if not _mixable(beat, vocal, fence.SAFE_STRETCH_LO, fence.SAFE_STRETCH_HI):
                    removed.append((beat, vocal))
    assert old_mixable > 0, "the grid must actually exercise mixable pairs (guards a hollow pass)"
    assert removed == [], f"widening REMOVED mixable pairs (must never happen): {removed[:10]}"


def test_widening_actually_adds_pairs():
    """Sanity/anti-hollow: the widened band must recover pairs the old band declined — otherwise the
    monotonicity test above could pass trivially on an unchanged band. Proves the band really widened."""
    grid = [float(b) for b in range(80, 162, 2)]
    recovered = [
        (beat, vocal)
        for beat in grid
        for vocal in grid
        if not _mixable(beat, vocal, OLD_LO, OLD_HI)
        and _mixable(beat, vocal, fence.SAFE_STRETCH_LO, fence.SAFE_STRETCH_HI)
    ]
    assert recovered, "the ±15% band recovered no new pairs — did the band actually widen?"


# ---------------------------------------------------------------- 2. CATALOG EDGE PAIRS


def _catalog_bpms() -> list[tuple[str, float]]:
    """(name, bpm) for every catalog song whose analysis file is present with a real bpm. Returns []
    when the local catalog/analyses aren't on disk (CI without the gitignored data/)."""
    manifest = _REPO / "services" / "api" / "data" / "library" / "manifest.json"
    if not manifest.exists():
        return []
    out: list[tuple[str, float]] = []
    for entry in json.loads(manifest.read_text(encoding="utf-8")):
        sid = entry.get("song_id")
        if not sid:
            continue
        ap = _REPO / "services" / "api" / "data" / f"{sid}.analysis.json"
        if not ap.exists():
            continue
        bpm = json.loads(ap.read_text(encoding="utf-8")).get("bpm")
        if bpm and bpm > 0:
            out.append((entry.get("name", sid), float(bpm)))
    return out


def test_catalog_edge_pairs_never_flip_mixable_to_declined():
    """The real catalog is where the widening bites: pairs whose folded one-sided stretch sat right at
    the OLD 0.89/1.11 edges are exactly the ones the change moves. For every ordered (beat, vocal) pair
    within 2% of an old edge, assert NONE flip mixable->declined — only declined->mixable is allowed.
    Skips gracefully (never hard-fails) when the gitignored analyses aren't on disk."""
    catalog = _catalog_bpms()
    if len(catalog) < 2:
        pytest.skip("catalog analyses not present (data/ is gitignored) — nothing to check")

    near_edge = 0
    flipped: list[str] = []
    recovered: list[str] = []
    for bname, beat in catalog:
        for vname, vocal in catalog:
            if beat == vocal:
                continue
            ratio = fence.best_stretch(beat, vocal)[0]  # folded one-sided stretch (nearest 1.0)
            if not (abs(ratio - OLD_LO) <= 0.02 * OLD_LO or abs(ratio - OLD_HI) <= 0.02 * OLD_HI):
                continue
            near_edge += 1
            old = _mixable(beat, vocal, OLD_LO, OLD_HI)
            new = _mixable(beat, vocal, fence.SAFE_STRETCH_LO, fence.SAFE_STRETCH_HI)
            if old and not new:
                flipped.append(f"{bname}({beat}) x {vname}({vocal}) ratio={ratio}")
            elif new and not old:
                recovered.append(f"{bname}({beat}) x {vname}({vocal}) ratio={ratio}")

    if near_edge == 0:
        pytest.skip("no catalog pair sits within 2% of an old band edge — nothing to check")
    print(f"\n[edge-pairs] {near_edge} near-edge pairs; {len(recovered)} recovered (declined->mixable):")
    for line in recovered:
        print("  recovered:", line)
    assert flipped == [], f"catalog pairs flipped mixable->declined (must never happen): {flipped}"


# ---------------------------------------------------------------- 3. SINGLE SOURCE OF TRUTH


def test_set_render_band_is_the_same_imported_fence_band():
    """workers/set_render.py must READ the band from fence, not keep its own copy — so a future retune
    of fence's SAFE_STRETCH band propagates to the set engine with zero extra edits. `is` (not just ==)
    proves it's the very object fence exports: a hardcoded literal in set_render would be a distinct
    float object and fail this, even at the same numeric value."""
    assert set_render.SAFE_STRETCH_LO == fence.SAFE_STRETCH_LO
    assert set_render.SAFE_STRETCH_HI == fence.SAFE_STRETCH_HI
    # the same object imported from fence (a from-import binds the name to fence's object), so the two
    # can never drift: change fence's constant and set_render's follows automatically.
    assert set_render.SAFE_STRETCH_LO is fence.SAFE_STRETCH_LO
    assert set_render.SAFE_STRETCH_HI is fence.SAFE_STRETCH_HI
