# Design — "Good-parts window": build the mix on the song's best ~90 seconds

_Date: 2026-07-09 · Status: approved (founder go) · Branch: `feat/house-bollywood-energy-sync`_

## Problem

Today the arrangement engine builds across the **entire** beat song. Song 1's beat runs start-to-finish, so a 7–9 minute beat makes a 7–9 minute mix with long beat-only stretches (measured: Anchor Point 5.8 min → 1.9-min gaps; Innerbloom 9.2 min → 3.0-min gaps). This is the founder's #1 quality gap: mixes feel "plain," long songs feel empty, and long-vs-short song length mismatch is unsolved.

Real DJs never play a whole track — they play the ~1–2 minutes that builds up to and lands on the song's big moment. This feature makes the app do the same.

## The approved shape (founder decisions)

- **Anchor:** the beat song's **main drop** (its biggest / most energetic drop — the payoff), where the vocal song's **signature hook** already lands (hook-on-drop, live + founder-confirmed).
- **Build up to it, don't cut cold:** the window starts with a **run-up before** the drop so the drop feels earned; the vocal's other parts fill the run-up, rising toward the hook.
- **Window length:** aim **~90s, flexible 60–120s**, snapped to clean phrase boundaries.
- **Method:** automatic selection anchored on signals the app already reads reliably (the beat's main drop + the marked hook), with the founder **hearing the final render** before it's locked (the existing ear-confirm loop — no manual marking).
- **Out of scope for this build:** the multi-song set / auto-transition feature (separate, next build); auto good-part detection on arbitrary uploads (V2); any change to Song 2 vocal-selection philosophy (hooks stay hand-marked; vocal parts as today).

## Core design: the window is the new canvas

The key move is to **crop and re-base Song 1's grid to the chosen window, then run the existing arrangement engine unchanged on that windowed grid.** The entire current pipeline (`synced_anchors`, hook-on-drop, `_produce_drops`, flourishes, stem moves, warp/beat-lock, validation) already operates against a `TrackAnalysis` grid and a `track_end`; point it at a 90-second grid instead of a 7-minute one and it "just works." This keeps the change small and preserves every ear-confirmed behavior.

### New / changed units

1. **`app/planner/window.py` (NEW — pure, isolated, testable).**
   - `choose_window(a1g, drops, opts) -> tuple[float, float] | None`
   - Picks the **main drop** = the highest-energy drop in `drops` (ranked via the existing per-bar energy curve; ties → the later one, so there's runway before it). Falls back to the loudest phrase anchor only if `drops` is non-empty but unranked.
   - Window = `[drop - runup, drop + tail]` targeting ~90s (clamped to 60–120s), snapped to Song 1 phrase-start downbeats (`a1g.phrase_starts`), clamped to `[0, track_end]`.
   - Runup takes the majority of the window (build-up dominant); tail is a short resolve after the drop.
   - Returns **`None`** when there is no confident main drop (empty `drops`, or low grid confidence) → caller keeps today's full-track behavior.
   - Constants (`_TARGET_SECS=90`, `_MIN_SECS=60`, `_MAX_SECS=120`, tail bars) live here, tunable by ear.

2. **`window_analysis(a1g, win_start, win_end) -> TrackAnalysis` (NEW — pure).**
   - Mirrors the existing `fence.retimed_analysis` copy pattern. Returns a copy of `a1g` whose `beats / downbeats / phrase_starts / sections / vocal_regions / energy_curve` are **restricted to `[win_start, win_end]` and shifted so the window starts at 0.0**. `bpm` unchanged.
   - Because this yields a normal `TrackAnalysis`, the whole downstream engine consumes it with no other changes; placement anchors, drops, stem moves and s1-regions all come out **window-relative (starting at 0)**.
   - Lives alongside `window.py` (or in `fence.py` next to `retimed_analysis` — decide in plan; prefer `window.py` to keep window logic together).

3. **`build_mix_plan` (CHANGED — `plan.py`, safe surface).**
   - After `arrangement_options`, compute `win = choose_window(a1g, opts["drops"], opts)`.
   - If `win` is not None **and** `_confident(a1g)`: build the windowed grid `a1w = window_analysis(a1g, *win)`, recompute the window-relative `opts` (anchors/drops/track_end/sections) from `a1w` via `arrangement_options`-style helpers, and run the existing arrangement on `a1w`. Record `window=(win_start, win_end)` and `bed_stretch` on the plan for render.
   - Else: today's exact path (full track). This is the fallback — never worse than now.
   - The vocal (Song 2 / `a2`) is untouched: hook still lands on the (now windowed) main drop; setup entries fill the run-up.

4. **`MixPlan` model (CHANGED — `models.py`, additive).**
   - Add `window: tuple[float, float] | None = None` — the Song-1 source-time span the bed is cropped to (None = full track, back-compat). Additive/optional so existing plans/tests are unaffected.

5. **Render (CHANGED — `workers/render.py`, DANGEROUS surface — confirm-and-apply).**
   - When `plan.window` is set, lay Song 1's bed starting at `win_start` for `win_end - win_start` seconds (accounting for the existing `bed_stretch` mapping), instead of the whole track. All placements / stem moves are already window-relative (start at 0), so they land over the cropped bed unchanged.
   - The only genuinely sensitive edit: cropping the bed. Everything else is the same render path.

6. **Validator (`services/api/app/planner/validate.py`, DANGEROUS surface — verify, likely no change).**
   - The plan is internally consistent and window-relative, so `validate_plan` / `validate_render` should pass as-is (single vocal, one bassline, no clipping, on-beat). **Must be re-checked**; only touch if it assumes bed length == full song. Prefer zero change here.

### Data flow

```
a1, a2 ─▶ arrangement_options ─▶ a1g (retimed grid), drops
                                   │
                          choose_window(a1g, drops)
                                   │
                    ┌──────────────┴───────────────┐
              window found                    None / low-conf
                    │                              │
        window_analysis(a1g, win)           (today's full-track path)
                    │                              │
     EXISTING engine on a1w (0-based)        EXISTING engine on a1g
     hook@drop, build-up, stem moves               │
                    └──────────────┬───────────────┘
                                   ▼
                    MixPlan(window=…, placements…, stem_moves…)
                                   ▼
                 render: crop bed to window ─▶ WAV ─▶ validate
```

## Edge / fallback states

- **No confident main drop** (empty `drops`, low `bpm_confidence`): `choose_window` returns None → full-track mix (today's behavior). Never worse than now.
- **Song shorter than the target window:** window clamps to `[0, track_end]` → ≈ the whole (short) song. Fine.
- **Drop near the very start** (no runup room): window start clamps to 0; runup shrinks. If runup collapses below a floor, treat as no-window (fallback) rather than a cold cut on bar 1.
- **Drop near the very end** (no tail room): tail shrinks to the track end; still valid.
- **Multiple strong drops:** pick the biggest. (Optional, later: Regenerate may pick a different strong drop's window for variety — not in this build.)
- **Movable master (`bed_stretch != 1.0`):** the window is computed on the retimed grid `a1g`; the render maps `win_start` back through `bed_stretch` to the source bed. Contained arithmetic; covered by a test on a movable-master pair.

## Testing

- **`window.py` unit tests:** synthetic `a1` with a known main drop + energy curve → window ~90s, ends on/just after the drop, starts on a phrase boundary, clamps at both bounds, returns None with no drop, handles drop-at-start / drop-at-end.
- **`window_analysis` unit tests:** cropping + 0-rebasing correctness — beats/downbeats/sections/energy filtered to the window and shifted; empty-grid safety.
- **Integration (real cached pairs, no cloud cost):** `build_mix_plan` on Father Ocean × {Dil Ye Bekarar, Maula Mere} → plan carries a `window`, mix length ≈ window, hook lands on the windowed drop, run-up before it; `validate_plan` / `validate_render` CLEAN.
- **Fallback integration:** a low-confidence / no-drop analysis → no window, today's plan reproduced (regression-locked).
- **Danger-file test (`render.py`):** with `plan.window` set, the rendered WAV length ≈ window length, single vocal, no clipping, on-beat; without `window`, byte-for-behavior identical to today.
- **Full regression:** all 302 backend + 39 web green; typecheck clean.

## Living docs to update (same PR)

- `docs/functional-spec.md` — mixes are now the ~90s "good part" that builds to the main drop; retire the "full-length mix is the hero output" line (superseded).
- `docs/technical-spec.md` — the window module + windowed-canvas architecture.
- `docs/implementation-plan.md` — mark the good-parts feature; drift-log entry.
- `docs/mix-recipe.md` — the good-window rule (anchor on the main drop, build up, ~90s).

## Safety summary (heavy path)

- Dangerous surfaces touched: `workers/render.py` (bed crop — the one real edit); `validate.py` (verify only, prefer no change). Both go through the independent adversarial safety review + founder confirm-and-apply before anything is written to them.
- Everything else (`window.py`, `window_analysis`, `plan.py`, `models.py`) is a safe surface.
- Fallback-to-today guarantees the change is strictly additive in effect: a song that can't be windowed renders exactly as it does now.
