# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-11 (**"Validate the drops, start the seams" brief: Task 1 (hook fallback removed) + Task 2 (marking tool built) + Task 3.1-3.4 (the set engine now beat-matches its seams) SHIPPED to the branch. Everything committed on `feat/house-bollywood-energy-sync`, NOT merged, NOT pushed. Suite: 395 backend green (fresh run at handoff). Two things wait on the founder's EAR: Der Lagi's hook (to un-move the tuning baseline) and the 18-song marking session (to produce the energy_drops precision/recall report). `render.py`/`validate.py`/`enabled`/Slice 2d ALL untouched.**)

## Where things stand (one breath)

This session shipped code (the previous four were diagnostics). **Task 1** removed the loudest-slice hook guess: a vocal donor with no hand-marked hook no longer lands its loudest slice on the drop (a guess measured ~28s off) — it uses its vocal regions as-is in song order. **The founder caught a real error in the first summary:** all five shipped catalog vocal donors are hookless (the 3 `hooks.py` marks are older Anchor Point songs, none shipped), so **every catalog vocal mix changed** — verified by diffing the Father Ocean × Der Lagi baseline (entries 2 & 3 swap which Der Lagi section they sing). **Task 2** built the marking instrument (a browser drop/hook marker + a precision/recall measurement script), but the actual REPORT is blocked on the founder's ~1hr marking session. **Task 3.1-3.4** turned the set stitcher from a dumb crossfade into a beat-matched one: the plan now persists the mix's own beat grid (3.1), a set picks one global tempo and declines outliers (3.2), and seams cut on phrase boundaries with downbeats aligned and stay clip-safe (3.3/3.4). **Task 4 (the crop) is correctly gated on Task 2's numbers** and was not started.

## In flight - done vs left

- **Nothing is half-built or red.** Every commit below is green and either safe-surface-only or a new dev tool.
- **Task 1 DONE (`plan.py` + `hooks.py` docstring):** loudest-slice hook fallback removed at all three no-hook sites; with-hook path unchanged (catalog hooks, when marked, still land on the drop). `ENGINE_VERSION m6.1→m6.2` (a real planner change — every hookless-donor catalog mix re-renders). Gate B re-baselined deliberately. Docs corrected after the founder's catch.
- **Task 2 DONE (the tool, not the report) (`scripts/`):** `mark_drops.html` (zero-install browser marker: D=drop, H/H=hook, CSV export, autosave, 6 catalog names embedded); `measure_drops.py` (reuses the shipped `fence.energy_drops`; reports precision/recall/offset; self-verified 100/100 perfect, 86/86 perturbed; **zero cloud**); `ground_truth/{drops_hooks.csv template, README}`.
- **Task 3.1-3.4 DONE (`models.py` + `window.py` + `routes/mix.py` + `workers/set_render.py`):** `MixPlan.out_downbeats/out_phrase_starts/mix_duration` (additive); `window.output_grid` (the referee's own derivation, canonical copy); `set_render.set_tempo_plan`/`global_master_tempo` (one tempo, decline outliers, band held); `assemble_beatmatched_set` + `_phrase_seam` (phrase-boundary, downbeat-aligned seams) + shared `_finalize` (peak-safe). All safe surface.
- **Left / next:** (1) **Der Lagi's hook** — needs the founder's timestamps (I can't listen); wiring it restores the moved baseline. (2) **The founder's ~1hr marking session** → run `measure_drops.py` → report precision/recall → **unblocks Task 4** (the crop: `crop_window()` pure fn, keep mixable edges, `WindowMove` gated off, confidence-throttled). (3) **The set-builder wiring** — a `/set` API + screen that renders each chosen mix at the one global tempo (3.2) then calls `assemble_beatmatched_set`; the engine is done, only the app plumbing + a way for the founder to HEAR a set remains. (4) Still pending from before: the founder's tuning week → flip `enabled=True` (sandbox first) → Slice 2d (pitch repair).

## Do first next session

1. **Get Der Lagi's hook from the founder** (two timestamps, start & end of the memorable line) and wire it into `hooks.py` — this un-moves the Father Ocean × Der Lagi tuning baseline that Task 1 shifted. Then optionally mark the other four donors' hooks the same way.
2. **If the founder has done the marking session:** run `python scripts/measure_drops.py --csv scripts/ground_truth/drops_hooks.csv`, report precision + recall + offset-in-bars plainly, and only THEN start Task 4 (gated by construction).
3. **If the founder wants to hear a set:** render two cached Father-Ocean-based mixes fresh (they now persist grids via 3.1, same tempo since both are FO-beat) and join them with `assemble_beatmatched_set` to a desktop WAV, so the beat-matched seam is audible before the full set-builder UI is wired.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **395 passed in ~64s** (was 384 at session start; +11: 2 window/grid, 4 tempo, 5 seam; the mix-route render test also gained the 3.1 grid assertions; net +11 with Task 1's −1/+1 test swap).
- **Golden gate re-verified explicitly:** `pytest tests/test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0 tests/test_set_render.py` → **17 passed** (disabled render still byte-identical to the m6.0 baseline; all 16 set tests green).
- **Zero cloud proven** for this session: `git diff 8592f01..HEAD` over the `.py` files has **no** `replicate`/`anthropic`/`requests`/`.run(` calls added (the only "Replicate" hit is a comment). Task 1 is pure planner logic; Task 2 tools read local cached analyses; 3.1 reads a WAV header (metadata, not analysis); 3.2/3.3 are arithmetic/DSP.
- **`git status` → clean.** 6 commits this session `d1b5b97..4b2fb0b`, all on `feat/house-bollywood-energy-sync`. **NOT pushed, NOT merged** (per the brief's "nothing pushed").
- **Web suite:** not run — no web/TS files touched this session (last known 39 web green).

## Open escalations / RE-VERIFY next session (claims, not settled facts)

- **🔴 The founder's tuning baseline MOVED (Father Ocean × Der Lagi).** Task 1 changed the middle/end vocal entries of every hookless-donor mix, Der Lagi included. This is a CLAIM the founder should confirm by ear, and the fix (mark Der Lagi's hook) needs the founder's input — I cannot listen. Do not let tuning continue against a moved reference without flagging it.
- **`render.py` + `validate.py` (dangerous surfaces) still carry the DISABLED Phase-0 chain.** Untouched this session. CLAIM to re-verify: the golden gate proves disabled == `m6.0` byte-for-byte — re-run `test_golden_enabled_false_is_byte_identical_to_m6_0` next session before trusting it (it was green at this handoff). The ENABLED path is still not-proven-safe until the founder's tuning week + a live ear-check.
- **`enabled` is FALSE and must STAY false** until the founder flips it after tuning. Slice 2d (pitch repair) parked; pitch pinned 0, so `rubberband` (GPL) is never called at mix time.
- **Task 2's precision/recall report and Task 4 are GATED** on the founder's marking session — not skipped, not done. A CSV in the repo (`scripts/ground_truth/drops_hooks.csv`) is a header-only template until then.
- **Branch not merged / not pushed.** The whole arc lives on `feat/house-bollywood-energy-sync`. A merge still needs the standard pre-merge review (and the still-owed R1-crossfade-relaxation adversarial re-verify noted in `technical-spec.md` "Known follow-ups").
