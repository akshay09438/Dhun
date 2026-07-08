# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-08 (**big build session — the House × Bollywood judgment, Steps 1–2 of 5, built and founder-ear-confirmed**). This is the session where the recipe from the founder's reference mashups became real code. All work is on branch **`feat/house-bollywood-energy-sync`** (off `feat/m5-live-control`), **NOT merged to main**. Suite green: **212 backend + 39 web, typecheck clean.**

## Where things stand (one breath)

The two V1 features (offline mix + live steering) remain built. This session added the **House × Bollywood judgment** — the arrangement now: lands the Bollywood vocal on the house track's real **DROP** (energy-sync); **builds** into each drop (filter + volume climb); lets **BOTH vocals trade** (Father Ocean is no longer stripped — it leads its own passages and keeps its vocal **lick ringing into each drop**; the Bollywood vocal owns the drops; the app decides who leads, keeping real passages and dropping scraps; one lead at a time); blends the trades with the outgoing vocal's **own natural decay** (no imposed fade, incoming enters full); and **throws an echo after each sung phrase** into its pause on the drops. A prerequisite bug was fixed (3 catalog vocals were analyzed before their vocal was split → the app never heard their singing → short, mid-word vocals; recomputed). **The founder listened to every render and approved each move.** Recipe + plan: [house-bollywood-recipe.md](house-bollywood-recipe.md), [house-bollywood-build-plan.md](house-bollywood-build-plan.md).

## In flight

- **No half-done code.** Every step this session is complete, tested (TDD), committed, and founder-confirmed by ear. Working tree is clean.
- **Steps DONE:** Phase A (energy-sync) · the produced drop (build + echo) · catalog vocal-detection repair · Step 1 (both vocals trade + natural hand-off) · Step 2 (echo throws, per-phrase).
- **Step 3 is the next piece, NOT started:** the app auto-**performing the four stems** (drop to just the beat, pull the bass out and slam it back, beat-up, breakdown) at musical moments — the live-steering moves, baked into the arrangement. Then Step 4 (vocal chops on drops) and Step 5 (the AI taste layer).
- **Suite state (RAN THIS SESSION):** backend `pytest -q` in `services/api` → **212 passed**; web `npm test` → **39 passed**; `npm run typecheck` → **clean**.

## Do first next session

1. **Decide the open safety item first (see Open escalations):** a fresh **adversarial safety review of the R1 relaxation** should run before this branch merges to main. It does NOT block building Step 3 on the branch, but it must be cleared before merge. Cheapest to do it now while the change is fresh.
2. **Build Step 3 — the app performs the four stems.** Follow the same rhythm that worked all session: design the move in plain language → founder okays → build test-first → (gate `render.py`/`validate.py` via confirm-and-apply + adversarial review if touched) → render on the real Father Ocean × Der Lagi pair → founder listens → tune by ear. The founder tunes constants live (e.g. how long a "pause" or a "ring" is), so keep the knobs named and easy to dial.
3. **How to render for the founder (no cloud cost):** the scratchpad script pattern used all session — load the two cached analyses, `build_mix_plan` (deterministic path, no `ANTHROPIC_API_KEY`), `render_mix`, copy the WAV to the OneDrive Desktop, open it. Bump `ENGINE_VERSION` in `routes/mix.py` each engine/plan change so no stale mix is served.

## Verification evidence (which checks ran, what they returned)

- **Ran at handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **212 passed in ~20s**. Root → `npm run typecheck` → **clean (tsc --noEmit, no errors)**. Root → `npm test` → **7 files, 39 passed**.
- **End-to-end, no cloud cost:** every iteration this session was rendered through the real `build_mix_plan` → `render_mix` on the cached Father Ocean × Der Lagi pair (deterministic path) and the referee (`validate_plan`/`validate_render`) returned CLEAN; the founder listened to each WAV on the Desktop and approved.
- All new behaviour is TDD'd (RED→GREEN each step); the safety-relevant echo-tail length and the crossfade-constant coupling are pinned by explicit tests.

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE (a CLAIM, not settled): the R1 relaxation is NOT cleanly adversarially cleared.** To allow the natural vocal hand-off, the referee's core "one lead vocal at a time" rule (`validate.py` R1) was loosened to permit a **bounded overlap** (Song 1's tail may run ≤ `fence.LEAD_XFADE_SECS` = 1.2s past Song 2's entry). The engine's guaranteed fade was REMOVED at the founder's direction — the no-mud guarantee now leans on the **source vocal's natural phrase-end decay** + the short bound. An adversarial reviewer cleared the earlier _fade_ version (found no exploit) and flagged only a constant-coupling gap (since closed by a drift-guard test); but the founder directed the final _no-fade_ model and **stopped the re-verify**, so the bounded-no-fade relaxation has **no clean verdict**. **A fresh adversarial pass on it MUST run before `feat/house-bollywood-energy-sync` merges to main.** Residual worst case: up to 1.2s of two full lead vocals IF a source vocal is at full level (not decaying) right at a hand-off — bounded, brief, and fine for the hand-verified catalog, but unproven for arbitrary songs.
- **The echo-tail R1 guard is plan-side, not referee-side:** `placement_end` has no echo term, so the referee can't see an echo tail. `plan._produce_drops` suppresses/limits echoes so a tail can't ring over a later lead; the coupling (`plan._ECHO_TAIL_BEATS` ≥ `render._ECHO_BEATS*_ECHO_TAPS`) is pinned by a test. Keep this true if the echo constants change.
- **Branch not merged; `main` is behind** (still at the M4 tip per the prior handoff). Merge deferred by the founder. Merging needs: the R1 re-verify above, and lock CORS in `config.py` to the real origin if deploying.
- **Tempo "fast-track" / movable-master NOT built** — Father Ocean × **Tere Bina** (the founder's #1 favourite) is still DECLINED by the app (too-far tempo). The plan (recipe §1.5) is to meet two songs at a shared tempo (stretch the house bed too) — deferred; it's a protected `render.py` change. Tere Bina is also not in the catalog.
- **Catalog analyses live only in gitignored `data/`** (not reproducible from git). The vocal-region repair this session patched those local JSONs; a fresh machine must re-ingest and **split-before-analyze** (the trap that caused the short-vocal bug), or add a self-heal guard (recompute `vocal_regions` when empty + stem present).
- **With You** recomputed to only 1 vocal region (131s continuous) → thin regenerate variety — minor follow-up.
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do not make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live.
**Founder ear-test loop (what worked all session):** render a WAV of Father Ocean × Der Lagi via the deterministic pipeline and open it from the Desktop — no browser, no cloud cost.
