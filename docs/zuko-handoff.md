# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-08 (**Step 3 Wave 1 built — the app auto-performs Song 1's beat with a bass pull-and-slam on every produced drop**). All work is on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main** (main is still at the M4d tip). Committed as `9fa2b01` and **pushed to origin**. Suite green (re-verified fresh at handoff): **269 backend + 39 web, typecheck clean.**

## Where things stand (one breath)

The two V1 features (offline mix + live steering) remain built, and the **House × Bollywood judgment** (Steps 1–2: energy-sync, both vocals trade, natural hand-off, per-phrase echo throws) plus the **movable-master tempo** and **beat-lock drift fix** (prior session) are built and founder-confirmed. **This session built Step 3 Wave 1**: the mix engine gained a per-stem "mixing board" — it can ride one of Song 1's bed stems (drums/bass/other) up/down over an on-beat window. Wave 1 ships the highest-impact move, the **bass pull-and-slam**: on every produced drop, the bass fades to silent across the build and slams back on the anchor with the vocal, so the drop hits with real punch instead of the beat staying flat. Additive `StemMove` + `MixPlan.stem_moves` (old plans default `[]`, render byte-identical); `fence.stem_moves_for_drops` emits the move on Song 1's real downbeat grid; the engine (`render.py`) gives each bed stem a gain envelope with a declick-safe slam; the referee (`validate.py`) gained on-beat/gain/never-all-muted checks. `ENGINE_VERSION m5i.1→m5j.0`.

**The heavy-path safety process caught three real issues, all fixed and re-verified** — this is the review process working as intended, not a red flag:

1. An early draft deferred vocal placement until after the bed treatments, which silently changed how a _later_ breath/sweep duck treated a _prior_ placement's vocal tail — breaking the "old mixes render identically" promise for multi-placement plans. **Fixed** by summing the enveloped stems first, then running the original pipeline verbatim; **re-confirmed byte-identical (max abs diff 0.000)** against the pre-Step-3 engine on multi-placement cases.
2. The never-all-muted guard sampled the timeline every ~50ms and could miss a hole between samples (a crossing-ramp case). **Fixed** with exact interval math (`_muted_spans` / `_all_stems_muted_somewhere`) — no sampling.
3. A focused re-review found the exact guard still modeled a stem's gain as the `min` of overlapping moves, while the engine `multiplies` them — so two overlapping _partial_ ducks on one stem could hide a hole the guard couldn't see (not reachable by Wave 1's single-pull-per-drop planner, but a real trap for Wave 2 or an AI-authored plan). **Fixed** by rejecting overlapping same-stem moves outright, which makes the guard's per-move math exactly correct.

Design doc: [step3 spec](superpowers/specs/2026-07-08-step3-stem-dynamics-design.md) (as-built note added at the top recording these two deviations). Recipe + plan history: [house-bollywood-recipe.md](house-bollywood-recipe.md).

## In flight

- **No half-done code.** Everything this session is complete, tested (TDD), committed (`9fa2b01`), and **pushed**. The working tree has one small uncommitted doc edit (functional-spec.md, made at this handoff) — see "Do first next session" step 0.
- **Founder ear-test is the open acceptance.** A fresh real render — `DER LAGI x Father Ocean - STEP3 bass pull-and-slam.wav` — is on the founder's Desktop. Referee-clean (`validate_plan`/`validate_render` both CLEAN), 3 produced drops (1:03 / 3:56 / 6:18), no clip (peak 0.891), slam measured ~190–350× the pulled-down level. **Founder has not yet confirmed by ear.** Heads-up already given to the founder: the _pull_ is often subtle on real songs (source bass is already quiet pre-drop) — the **slam** carries the effect; if it reads too subtle/abrupt/deep, the fix is a tuning pass on the pull depth/window, not a rebuild.
- **Step 3 Wave 2 is NOT started:** cut-to-just-drums, beat-up, breakdown — same primitive, same proven engine, no new engine surgery. Gated on the founder confirming Wave 1 sounds right first.
- **Suite state (RAN FRESH AT HANDOFF, not carried over from mid-session):** backend `pytest -q` in `services/api` → **269 passed**; web `npm test` → **39 passed (7 files)**; `npm run typecheck` → **clean (tsc --noEmit, no errors)**.

## Do first next session

0. **Commit the functional-spec.md update** made at this handoff (Step 3's user-facing description — the bass pull-and-slam — folded into the "IN PROGRESS" paragraph; "Still to build" now correctly says "Step 3 Wave 2"). It's staged-but-uncommitted in the working tree; this handoff commit includes it.
1. **Get the founder's ear-test verdict** on the Desktop render before building anything further. If they like it: proceed to Wave 2. If the pull/slam needs tuning: it's a by-ear knob pass on `fence.stem_moves_for_drops` (window size) and/or the pull depth — no architecture change.
2. **Build Step 3 Wave 2** (after the founder okays Wave 1): cut-to-just-drums, beat-up, breakdown, each a new `fence` helper placed at a musical moment the app already detects (section boundaries), using the SAME `StemMove` primitive and the SAME (now-hardened) referee guard. No new engine surgery expected. Same rhythm: design the move in plain words → founder okays → build test-first → confirm-and-apply + independent test-author + adversarial quorum on the two protected files → render the real pair → founder listens.
3. **Clear the open safety item before any merge to main** (see Open escalations, carried forward unchanged): the pre-existing **R1-relaxation** (bounded hand-off overlap, no engine fade) still has **no clean adversarial verdict**. Does NOT block further branch work, but MUST be cleared before merge.
4. **How to render for the founder (no cloud cost):** the scratchpad script pattern used this session — load the two cached analyses, `build_mix_plan` (deterministic path; `os.environ.pop("ANTHROPIC_API_KEY")` forces the free rules path), `render_mix`, copy the WAV to the OneDrive Desktop under a **fresh, distinct filename** (same-name overwrites get served from the OS/OneDrive cache). Bump `ENGINE_VERSION` in `routes/mix.py` on each engine/plan change so no stale mix is served (now at **`m5j.0`**).

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at this handoff** (not reused from mid-session): `services/api` → `.venv/Scripts/python -m pytest -q` → **269 passed in ~23s**. Root → `npm test` → **7 files, 39 passed**. Root → `npm run typecheck` → **clean (tsc --noEmit, no errors)**.
- **End-to-end, no cloud cost, on the real Father Ocean × Der Lagi pair** (deterministic rules path): `build_mix_plan` → 3 produced drops (63.0s / 236.1s / 377.7s) each carrying one bass `StemMove`; `validate_plan` → **CLEAN**; `render_mix` → 476.3s WAV, peak 0.8912 (no clip), not silent; `validate_render` → **CLEAN**; measured bass-band energy: pull windows ~0.0004–0.0007, post-slam ~0.13–0.15 (**~190–350× louder** on the slam). Copied to the founder's Desktop for the ear-test (not yet confirmed).
- **The three fixes above were each independently verified**, not just applied: Fix 1 by a fresh adversarial re-review that rendered multi-placement no-move plans through both the old (`git show HEAD`) and new engine and measured **max abs diff = 0.000**; Fix 2/3 by constructing the reviewers' exact breach plans and confirming the referee now flags them (`test_validate_flags_crossing_ramp_silent_hole`, `test_validate_flags_overlapping_same_stem_moves`) while the real Wave-1 plan (non-overlapping, far-apart pulls) still validates clean (`test_validate_accepts_nonoverlapping_same_stem_moves`).
- **Both protected files** (`workers/render.py`, `services/api/app/planner/validate.py`) went through confirm-and-apply (founder approval recorded/cleared, twice — once for the initial build, once for the re-review fix) with independently-authored tests and a documented adversarial trail (3-lens quorum + a focused re-review).

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE (a CLAIM, not settled — carried forward unchanged from prior sessions): the pre-existing R1 relaxation is still NOT cleanly adversarially cleared.** To allow the natural vocal hand-off, `validate.py` R1 was loosened to permit a bounded overlap (Song 1's tail may run ≤ `LEAD_XFADE_SECS`=1.2s past Song 2's entry) WITHOUT an engine-guaranteed fade — it leans on the source vocal's natural decay. A fresh adversarial pass on the **bounded-no-fade** relaxation MUST run before `feat/house-bollywood-energy-sync` merges to main. Not touched this session.
- **Founder ear-test open (this session's new item):** the Step 3 bass pull-and-slam render is on the Desktop, referee-clean, but **not yet confirmed by ear.** Do not build Wave 2 before this lands — the founder may want the pull/slam tuned first.
- **Ear-test residuals from prior sessions (human-gated, not safety, still open):** (a) Tere Bina's vocal sits at the safe-band edge (house-protected minimal move) — if it reads too warbly, `fence.HOUSE_SLOW_MAX`/`HOUSE_SPEED_MAX` can be raised. (b) An occasional per-bar beat-lock excursion up to ~15% for ~1.7s (transient, from the wider grip band) — narrow `fence.WARP_LO/HI` if any single spot sounds momentarily wobbly.
- **Branch not merged; `main` is behind** (still at the M4d tip). Merge deferred by the founder. Merging needs: the R1 re-verify above, and lock CORS in `config.py` to the real origin if deploying.
- **Catalog + cached analyses live only in gitignored `data/`** (not reproducible from git). A fresh machine must re-ingest and **split-before-analyze** (the trap that causes empty vocal_regions → short mid-word vocals).
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do not make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live.
**Founder ear-test loop (what worked this session):** render a WAV of the real pair via the deterministic pipeline and open it from the Desktop under a fresh filename — no browser, no cloud cost.
