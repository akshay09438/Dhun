# Phrasing alignment — design spec

**Date:** 2026-07-10
**Status:** ⚠️ BUILT then REVERTED (2026-07-10) — kept as a historical record. The fixed-origin 8-bar grid (`downbeats[::8]`) pulled vocals 1–3 bars OFF the real drops because a song's phrasing is offset by its intro (Anchor Point drops at bars 43/61/97/121/139, none a multiple of 8). If revisited, anchor the grid to the music (a detected drop / first strong downbeat), never bar 0. See implementation-plan drift log 20th/21st.
**Branch:** `feat/house-bollywood-energy-sync`
**Blast radius:** HEAVY (architectural — governs all placement across the arrangement brain), but implementable on SAFE surfaces (`fence.py` / `plan.py`); the referee (`validate.py`) is NOT touched.

## Problem

Real DJs make changes on the musical "turn of phrase" — the downbeat of bar 1 of an 8-bar (or 4-bar) block. A change that lands mid-phrase (bar 5/6) sounds abrupt. Our mixes leak mid-phrase, which is a big part of why the Anchor Point mashups sound worse than the real YouTube remixes of the same pairs.

An investigation (2026-07-10) mapped exactly where positions are decided today. Key facts:

- `analysis.phrase_starts = downbeats[::8]` (every 8th downbeat = an 8-bar phrase boundary). `phrase_starts ⊆ downbeats`.
- The **anchor candidate pool** (`fence.candidate_drops`) is already phrase-aligned, and the **AI path** (`plan._ai_arrange`) snaps to it. But:
  - **`fence.energy_drops`** (fence.py:331) returns _any_ downbeat at an energy rise — not phrase-aligned.
  - **`fence.synced_anchors`** (fence.py:349-351) prefers such a drop, and **`plan._default_arrangement`** (the RULES path — what the deterministic goodnight batch used) uses that anchor directly with no re-snap (plan.py:237).
  - **Every auto beat-move window** (`stem_moves_for_drops`, `_best_energy_window` → `beat_up_moves`/`breakdown_moves`) and the **produced-drop build** (`_safe_build_bars`) are computed as "N bars before the anchor" on the raw downbeat grid → arbitrary (mid-phrase) downbeats.
- **The referee needs no change to ALLOW phrasing:** R3/R7 accept any downbeat, and phrase boundaries are downbeats, so a phrase-snapped plan passes unchanged.

## Goal

Every change in a mix lands on a phrase boundary:

- **8-bar grid (the big moments):** every vocal entry, the produced-drop build, and the drop itself.
- **4-bar grid (the finer moves):** the auto beat moves — beat-up, breakdown, and the "drop to just the beat" cut — their start/end boundaries.

No change lands mid-phrase. Result: the abrupt transitions go away; the mixes move toward the real-remix feel.

## Design

### The phrasing ruler (one source of truth)

A single shared helper in `fence.py`, used by every position-producing site — so all changes obey the same phrasing and cannot drift apart:

```
snap_to_phrase(t, downbeats, n) -> float
```

Returns the nearest downbeat that is on the n-bar grid (n=8 → an 8-bar phrase start = `downbeats[::8]`; n=4 → `downbeats[::4]`). Uses the (possibly retimed) grid `a1g.downbeats` so it is correct on the movable-master path. Graceful fallback: if the grid is missing/thin, return `t` unchanged (never crash, never decline a mix over phrasing).

### Grid assignment

| Change                             | Grid  | Where (from the map)                                                                |
| ---------------------------------- | ----- | ----------------------------------------------------------------------------------- |
| Vocal entry anchors                | 8-bar | `energy_drops` → `synced_anchors` → `_default_arrangement`; AI path already aligned |
| The drop moment (placement anchor) | 8-bar | anchor snap (item 1/2)                                                              |
| Beat-up window                     | 4-bar | `_best_energy_window` via `beat_up_moves`                                           |
| Breakdown window                   | 4-bar | `_best_energy_window` via `breakdown_moves`                                         |

**Not snapped (deliberately) — the gradual ramps:** two moves are _gradual fades into an already-aligned hard edge_, so they need no snapping:

1. The produced-drop **build** (the multi-bar filter/volume climb, rendered in `render.py`) ramps up INTO the drop anchor.
2. The **"drop to just the beat" cut** (`stem_moves_for_drops`) ramps the bass and melody _down_ — a genuine decline, per the standing "lower, never cut" rule — with its only hard change being the bass **slam at the anchor**.

In both, the abrupt moment is the drop/slam at the anchor, which is already 8-bar-aligned (item 1/2). The ramps themselves are not abrupt, so aligning their starts to the 4-bar grid buys nothing audible and, for the 2-bar cut, would collapse it under the grid. Leaving them also keeps the change off `render.py`. Same result: nothing lands abruptly mid-phrase.

### The phrase-wins rule (founder-approved)

When a detected drop (`energy_drops`) or a chosen anchor is a downbeat but **not** on the 8-bar grid, snap it to the **nearest 8-bar phrase start**. In well-produced music the drop _is_ the turn of phrase, so this normally lands exactly on the drop; when the analysis is slightly off, the phrase line is almost always the true drop the analysis missed — so phrasing wins. This also strengthens the upcoming hook-on-drop work.

Snapping `energy_drops` upstream propagates through `synced_anchors` and `_default_arrangement`, fixing the vocal-entry leaks at their source. Placement anchors are additionally guaranteed on the 8-bar grid as a belt-and-suspenders re-snap in both arrangement paths.

### Application sites (each place a position is decided)

1. `fence.energy_drops` — snap each returned drop to the nearest 8-bar phrase start.
2. `fence.synced_anchors` / `plan._default_arrangement` — ensure the final `Placement.anchor` is on the 8-bar grid (inherited once #1 lands; add a guaranteed re-snap).
3. **Beat-up and breakdown windows** (`fence._best_energy_window` via `beat_up_moves` / `breakdown_moves`): only consider windows whose start downbeat is on the **4-bar grid** (index a multiple of 4). Since the widths are 4 and 8 bars, both edges then land on the 4-bar grid — so the duck AND the return (the beat kicking back in) sit on phrase lines.
4. **The produced-drop build ramp and the drop's cut ramps are left as-is** (see "Not snapped" above) — gradual fades into the already-8-bar-aligned slam; no `render.py` change and no `stem_moves_for_drops` snapping.

### Safe surface

All edits are in `fence.py` and `plan.py` (safe). `validate.py` (the referee) is **not** touched — phrase-snapped positions are downbeats, which R3/R7 already accept. No confirm-and-apply / dangerous-file ceremony is required.

## Acceptance criteria

- `snap_to_phrase` returns the nearest n-bar grid point; idempotent (snapping an already-aligned point is a no-op).
- Every `Placement.anchor` in a produced plan is on the 8-bar grid (within `BEAT_TOLERANCE_SECS`).
- Every `StemMove.start`/`.end` is on the 4-bar grid.
- The produced-drop build start is on the 8-bar grid.
- A pair whose drops already sit on phrase boundaries renders unchanged (no needless churn).
- Graceful: a song with missing/thin `phrase_starts` still produces a valid plan (falls back, never declines over phrasing).
- Integration: re-render the three Anchor Point mixes (05 Dil Ye Bekarar, 09 Jee Karda, 10 Maula Mere) — no vocal entry or move lands mid-phrase; `validate_plan`/`validate_render` CLEAN, no clip. The four Father Ocean mixes (01–04) still validate clean.

## Scope / non-goals

**In scope:** _where_ (timing) every change lands — snapping to the phrase grid. Bump `ENGINE_VERSION`.

**Out of scope (separate upcoming builds, not this one):**

- **Hook-on-drop** — _which_ vocal part lands on the drop (the signature hook). Different build.
- **Strip-beat-vocal** — muting a vocal-heavy beat's own vocal. Different build.
- **Referee enforcement of phrasing** — a new `validate.py` rule that _rejects_ a non-phrase position. Deferred; planner-only snapping achieves the goal on a safe surface. Can be added later as a guardrail if wanted.

## Testing

- Unit tests for `snap_to_phrase` (nearest grid point, idempotence, fallback on empty grid, movable-master retimed grid).
- Plan-level tests asserting the acceptance criteria above (anchors on 8-bar, moves on 4-bar, build on 8-bar).
- Regression: a pre-aligned pair renders identically; the existing suite stays green.
- End-to-end on the real Anchor Point pairs (local/cached, no cloud cost): assert grid alignment + clean validation, then a founder ear-test.
