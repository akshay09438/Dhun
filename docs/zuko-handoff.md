# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-08 (**movable-master tempo built + beat-lock drift fixed — the founder's #1 pair, Father Ocean × Tere Bina, now plays and stays on the beat**). All work is on branch **`feat/house-bollywood-energy-sync`** (off `feat/m5-live-control`), **NOT merged to main** (main is still at the M4d tip). Suite green: **240 backend + 39 web, typecheck clean.**

## Where things stand (one breath)

The two V1 features (offline mix + live steering) remain built, and the **House × Bollywood judgment** (Steps 1–2: energy-sync, both vocals trade, natural hand-off, per-phrase echo throws) is built and founder-confirmed from the prior session. **This session added the movable-master tempo** so far-apart pairs can mix at all: when the one-sided lock would be out of the safe band, the app meets the two songs at a shared tempo — **house-protective** (founder call): the house moves the MINIMUM (bounded, never dragged down), the guest vocal takes the rest. Additive `MixPlan.bed_stretch`; the engine pre-stretches Song 1's whole bed; the referee rescales the grid + guards the house band and tempo consistency. Two adversarial-review must-fixes (F1 engine/referee gate mismatch, F2 referee independence) were found + fixed + re-verified. **Then two follow-on fixes:** (a) a predrop-lick crossfade **rounding** bug that wrongly declined movable pairs; (b) the **beat-lock drift** the founder heard on Tere Bina at ~4:18 — root-caused to the per-bar grip band being == the global stretch band, so a vocal near a stretch edge couldn't lock and drifted; fixed with a **wider per-bar grip band** (`fence.WARP_LO/HI`), which also fixed Der Lagi (1/3→3/3) and Tujhe (2/3→3/3). **Tere Bina was ingested** (split cache-hit from a prior test + one analysis call) and **added to the catalog**. Recipe + plan history: [house-bollywood-recipe.md](house-bollywood-recipe.md); this session's specs/plans in [docs/superpowers](superpowers/).

## In flight

- **No half-done code.** Every change this session is complete, tested (TDD), committed, and the working tree is **clean**. Both protected-file changes (movable-master render/validate; the R7 grip widening) went the full careful route — independent test-author + adversarial review + founder confirm-and-apply (approvals recorded/cleared).
- **Founder ear-test is the open acceptance:** fresh **Father Ocean × Tere Bina** and **× Der Lagi** mixes are on the founder's Desktop (the Tere Bina one under a NEW name — `TERE BINA x Father Ocean - NEW FIXED on-beat.wav` — because the same-name overwrite was being served from cache). The founder is about to listen; **Step 3 begins after they confirm.**
- **Step 3 is the next build, NOT started:** the app auto-**performing the four stems** (drop to just the beat, pull the bass out and slam it back, beat-up, breakdown) at musical moments. It is **designed and committed** ([step3 spec](superpowers/specs/2026-07-08-step3-stem-dynamics-design.md)) but no code written — it touches `render.py` (protected).
- **Suite state (RAN THIS SESSION):** backend `pytest -q` in `services/api` → **240 passed**; web `npm test` → **39 passed (7 files)**; `npm run typecheck` → **clean**.

## Do first next session

1. **Build Step 3 — the app performs the four stems** (the founder's stated next step, after their ear-test lands). Follow the design at [2026-07-08-step3-stem-dynamics-design.md](superpowers/specs/2026-07-08-step3-stem-dynamics-design.md): a general per-stem gain-envelope layer in `render.py` (🔒), proven first with the **bass pull-and-slam** into the drop, then cut-to-just-drums / beat-up / breakdown. Same rhythm that worked all session: design the move in plain words → founder okays → build test-first → confirm-and-apply + independent test-author + adversarial quorum on the protected engine → render the real pair → founder listens → tune by ear.
2. **Clear the open safety item before any merge to main** (see Open escalations): the pre-existing **R1-relaxation** (bounded hand-off overlap, no engine fade) still has **no clean adversarial verdict**. It does NOT block Step 3 on the branch, but MUST be cleared before merge.
3. **How to render for the founder (no cloud cost):** the scratchpad script pattern used all session — load the two cached analyses, `build_mix_plan` (deterministic path; `os.environ.pop("ANTHROPIC_API_KEY")` forces the free rules path), `render_mix`, copy the WAV to the OneDrive Desktop under a **fresh, distinct filename** (same-name overwrites get served from the OS/OneDrive cache — the founder saw this). Bump `ENGINE_VERSION` in `routes/mix.py` on each engine/plan change so no stale mix is served (now at **`m5i.1`**).

## Verification evidence (which checks ran, what they returned)

- **Ran at handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **240 passed in ~25s**. Root → `npm test` → **7 files, 39 passed**. Root → `npm run typecheck` → **clean (tsc --noEmit, no errors)**.
- **End-to-end, no cloud cost:** the movable-master path was rendered through the real `build_mix_plan` → `render_mix` on the cached pairs each iteration; the referee (`validate_plan`/`validate_render`) returned CLEAN. Confirmed beat-lock after the drift fix: **Father Ocean × {Tere Bina, Der Lagi, Tujhe} = 3/3 placements beat-locked, all validate CLEAN** (was Tere Bina 0/3, Der Lagi 1/3, Tujhe 2/3).
- **Both protected changes** (movable-master `render.py`/`validate.py`; the R7 grip widening in `validate.py`) had independently-authored failing tests and an adversarial review returning `safe` / all-must-fixes-closed before apply.

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE (a CLAIM, not settled): the pre-existing R1 relaxation is still NOT cleanly adversarially cleared.** From an earlier session: to allow the natural vocal hand-off, `validate.py` R1 was loosened to permit a bounded overlap (Song 1's tail may run ≤ `LEAD_XFADE_SECS`=1.2s past Song 2's entry) WITHOUT an engine-guaranteed fade — it leans on the source vocal's natural decay. A fresh adversarial pass on the **bounded-no-fade** relaxation MUST run before `feat/house-bollywood-energy-sync` merges to main.
- **Ear-test residuals (human-gated, not safety):** (a) **Tere Bina's vocal warble** — it sits at the safe-band edge because the house is protected (minimal move); if the founder finds the whole vocal too warbly, the fix is to let the house move a bit more (raise `fence.HOUSE_SLOW_MAX`/`HOUSE_SPEED_MAX`, or add a small headroom to `tempo_plan`). (b) **Per-bar warble** from the wider beat-lock grip — an occasional edge bar now stretches up to ~15% for ~1.7s (transient) to hold the beat; if any single spot sounds momentarily wobbly, narrow `fence.WARP_LO/HI`. Both are by-ear knobs.
- **Branch not merged; `main` is behind** (still at the M4d tip). Merge deferred by the founder. Merging needs: the R1 re-verify above, and lock CORS in `config.py` to the real origin if deploying.
- **Founder's clarified taste (recorded):** a long continuous vocal is FINE as long as it stays on the beat — the earlier "shorten/spread the vocal" idea was NOT the fix (drift was). Non-linear / shorter-placement remains a possible future taste option, not a bug.
- **Catalog + Tere Bina analyses live only in gitignored `data/`** (not reproducible from git). Tere Bina's manifest entry + stems + analysis are local-only. A fresh machine must re-ingest and **split-before-analyze** (the trap that causes empty vocal_regions → short mid-word vocals).
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do not make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live.
**Founder ear-test loop (what worked all session):** render a WAV of the real pair via the deterministic pipeline and open it from the Desktop under a fresh filename — no browser, no cloud cost.
