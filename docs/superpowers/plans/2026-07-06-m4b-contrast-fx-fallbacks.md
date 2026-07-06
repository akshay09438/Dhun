# M4 Slice B — Contrast + Subtle FX + Confidence Fallbacks — Implementation Plan

> **For agentic workers:** implement task-by-task, TDD, commit per task. Dangerous files (Task 4 `validate.py`, Task 5 `render.py`) go through the confirm-and-apply flow + independent review.

**Goal:** Both songs trade vocals (keep Song 1's own voice in a gap), one subtle filter-sweep into a big entry, and the arranger plays safer on shaky songs.

**Architecture:** Additive on M4a. Two new plan dimensions (`MixPlan.s1_vocal_regions`, `Placement.fx`); the driver picks them (confidence-gated); the referee guarantees Song-1 and Song-2 vocals never overlap; the engine mixes Song 1's vocal stem into the gap spans and applies a rising low-pass sweep before a flagged entry.

## Global Constraints

- Additive only — M3/M4a cached `*.mixplan.json` must still parse.
- One voice at a time is the load-bearing rule: Song 1's vocal spans must never overlap any Song 2 placement window. The referee enforces it via the shared `fence.placement_end`.
- Effects subtle-only (one `sweep_in` per mix). Bed-only DSP; −1 dBFS normalize + clip guard unchanged.
- Dangerous files gated (approval + adversarial review). Bump `ENGINE_VERSION` → `m4b.1`.
- Backend tests from `services/api` via `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: Models — `s1_vocal_regions` + `Placement.fx` (non-dangerous)

**Files:** `services/api/app/models.py`; test `services/api/tests/test_models.py`.

- Add `Placement.fx: str | None = None`; `MixPlan.s1_vocal_regions: list[tuple[float, float]] = []`.
- Test: a plan with `s1_vocal_regions` + a placement `fx="sweep_in"` round-trips; an M4a JSON without them still parses (both default empty/None).

### Task 2: Fence — contrast windows (non-dangerous)

**Files:** `planner/fence.py`; test `tests/test_fence.py`.

- `contrast_windows(a1, placements, stretch, min_secs=6.0) -> list[tuple[float,float]]`: the beat-only gaps between consecutive Song-2 placements (using `placement_end`), intersected with Song 1's own `vocal_regions` (where S1 actually sings), each shrunk by a small margin so it never touches the neighbouring S2 vocals; only gaps ≥ `min_secs` returned.
- Tests: returns a window inside a real gap where S1 sings; returns [] when S1 never sings in any gap; windows never touch the S2 placements.

### Task 3: Driver — contrast + one FX + confidence gating (non-dangerous)

**Files:** `planner/plan.py`; test `tests/test_plan.py`.

- `_confident(a1) -> bool`: `a1.bpm_confidence is None or a1.bpm_confidence >= 0.5` (grid trustworthy). (sections_confidence is pinned 0.6; gate on the grid + vocals where relevant.)
- In `build_mix_plan`: after placements + dedupe, if `_confident(a1)`: pick **one** contrast window (`fence.contrast_windows`, best/longest) → `s1_vocal_regions=[win]`; set `fx="sweep_in"` on the single highest-anchor (biggest) re-entry placement (not the first). If **not** confident: cap to ≤2 placements, `s1_vocal_regions=[]`, clear all `fx` and `beat_breath` (play safe). Notes mention the contrast.
- Tests: confident pair → `s1_vocal_regions` non-empty and inside a gap where S1 sings, exactly one placement has `fx="sweep_in"`; a low-`bpm_confidence` a1 → no contrast, no fx, ≤2 placements, no breath.

### Task 4 (DANGEROUS — approval): Referee — S1↔S2 vocal no-overlap (`validate.py`)

**Files:** `planner/validate.py`; test `tests/test_validate.py`.

- In `validate_plan`: for each `s1_vocal_regions` span `(s,e)`: flag if `e <= s` (empty); flag if it overlaps any Song-2 placement window `[p.anchor, placement_end(p...)]` — "Song 1 and Song 2 vocals overlap (R1)".
- Tests: an S1 region overlapping an S2 placement is flagged; an S1 region sitting cleanly in a gap passes; empty S1 region flagged.

### Task 5 (DANGEROUS — approval): Engine — mix S1 vocal + `sweep_in` (`render.py`)

**Files:** `workers/render.py`; test `tests/test_render.py`.

- Add `_SWEEP_LO_HZ=300`, `_SWEEP_STEPS=8`, `_sweep_bed(seg, sr) -> seg` (rising low-pass via `scipy.signal.butter`/`sosfilt` across sub-blocks).
- In `render_mix`: (a) for a placement with `fx == "sweep_in"`, replace the one bar before its anchor with `_sweep_bed(that bar)` (after any breath-duck); (b) after placing Song-2 vocals, for each `plan.s1_vocal_regions` span, decode `song1_stems["vocals"]`, slice `[s,e]`, edge-fade, and add to `bed[s:e]` (no stretch — it's already Song 1's tempo). `_placements_of`/scalar path unchanged; `getattr(plan,'s1_vocal_regions',[])` so duck-typed/old plans are fine.
- Tests: an S1-vocal span raises energy in that span vs the bare bed there; `sweep_in` reduces high-frequency content in the pre-entry bar then it returns (brightness dips then recovers); still no clip; a plan with neither behaves exactly as M4a.

### Task 6: Route — pass S1 vocals + version (non-dangerous)

**Files:** `routes/mix.py`; test `tests/test_mix_route.py`.

- `_S1_STEMS` stays drums/bass/other for the bed, but pass a 4-key dict including `"vocals"` into `render_mix` (bed sums only 3; engine reads `["vocals"]` for contrast). `ENGINE_VERSION="m4b.1"`. Precondition already requires S1 split (all stems present).
- Test: a mix with a confident pair completes and the served plan carries `s1_vocal_regions`.

### Task 7: Web — Song-1 vocal + FX markers (non-dangerous; `Mix.test.tsx` is a guarded test file → approval)

**Files:** `apps/web/src/lib/api.ts`, `components/Mix/Mix.tsx`, `Mix.module.css`, `Mix.test.tsx`.

- DTO: `MixPlanDTO.s1_vocal_regions: [number,number][]`, `PlacementDTO.fx: string | null`.
- Timeline: render S1-vocal blocks in the vocal lane in a **distinct colour** (`data-testid="s1-vocal-block"`); a small FX tick on a placement with `fx`.
- Test: a plan with one `s1_vocal_regions` renders one `s1-vocal-block`.

### Task 8: Docs

- Mark **M4 Slice A ✅ live-confirmed done**; Slice B as-built (functional + technical + implementation-plan + drift log). Bump test counts.

## Self-Review

- Coverage: contrast (T2/T3/T4/T5/T7), FX (T3/T5/T7), confidence gating (T3), the R1 S1↔S2 guarantee (T4). ✓
- Additive/back-compat: T1 + duck-typed getattrs in T5. ✓
- Dangerous surfaces T4/T5 gated. ✓
