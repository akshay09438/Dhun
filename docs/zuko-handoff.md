# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-09 (**Step 3's four beat moves DONE + confirmed; Step 4 "vocal chops" BUILT but its independent safety review is INCOMPLETE — in flight**). All work is on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main**. Everything is committed + pushed to origin. Suite green: **293 backend + 39 web, typecheck clean** (re-run fresh at handoff, with the in-flight vocal-chops code in the tree).

## Where things stand (one breath)

This session finished the **Step 3 "mixing board"** — all **four auto-performed beat moves** are built, verified on the real Father Ocean × Der Lagi pair, and founder-confirmed: **bass pull-and-slam**, **drop to just the beat**, **beat-up** (melody ducks, beat drives), **breakdown** (drums+bass fade to a simmer, then kick back). Each reused the existing StemMove engine — **no `render.py`/`validate.py` edits** — so they went the fast safe-surface route. Along the way three real ear-test bugs were found + fixed (a stem hollowing out under Father Ocean's own vocal; an abrupt cut instead of a gradual lower — now a **standing rule: a continuous element is only ever LOWERED, never CUT, except at a real transition the song earns**; and a pre-existing "build" tipping a natural source breakdown into true silence). Then **Step 4 "vocal chops on the drop" was built** (see the ⚠️ below) — the FIRST change since the beat moves to touch a dangerous file (`render.py`).

## In flight

- **⚠️ VOCAL CHOPS IS IN FLIGHT — BUILT, MY-VERIFIED, but NOT independently safety-reviewed and NOT ear-tested.** It is committed to the branch (commit `a405ad8`) **only to preserve the work cleanly**, with a loud "do not trust/merge until reviewed" flag in the commit message. What it does: `render._chop_pattern` re-fires the vocal's first syllable rhythmically over the biggest drop's first bar ("dum-da-ra-dum"); it replaces bar 1 only, so the placement length — and the referee's overlap math — are unchanged (`validate.py` was NOT touched; `render.py` is the only dangerous edit). **My own checks pass** (suite green; no-chop path byte-identical 0.0 diff; real pair renders CLEAN, peak 0.891, no clip, chop at 3:56 on the Desktop as `Der Lagi x Father Ocean - vocal-chops.wav`). **What did NOT happen:** the independent test-author (writing `test_render.py` chop tests) and the adversarial reviewer were dispatched and were STILL RUNNING when the session closed — **neither verdict returned**. So the dangerous-surface change has not had its independent review, and the founder has not heard it.
- **Everything else this session is fully done, committed, and pushed** (the four beat moves: commits through `0652439`). Working tree is **clean** after the in-flight commit.
- **Suite state (RAN FRESH AT HANDOFF):** `services/api` → `pytest -q` → **293 passed**; root → `npm test` → **39 passed (7 files)**; `npm run typecheck` → **clean**.

## Do first next session

1. **FINISH THE VOCAL-CHOPS SAFETY REVIEW before trusting or building on it.** Re-dispatch the **independent test-author** (add the chop tests to `services/api/tests/test_render.py` — rhythmic-onsets-in-the-chopped-bar, length-unchanged, no-chop byte-identical, no-clip, `_chop_pattern` edge cases) and a fresh **adversarial-safety-reviewer** on the `render.py` change (attack: could `_chop_pattern` ever change `len(voc)` and break R1 overlap? could summed fragment copies clip? edge inputs — empty/1-sample vocal, bpm 0, vocal shorter than a bar?). Fold in `test_render.py`, address any findings. Only then is Step 4 real. The prompts used this session are in the two dispatched agents (aa8c5413…, a506f0073…) if resumable; otherwise re-write from the design.
2. **Then founder ear-test the chops** (the Desktop render, chop at **3:56**) and tune by ear (`render._CHOP_SECS` fragment length, `_CHOP_INTERVAL_BEATS` rhythm, whether it fires on one drop or several).
3. **Then Step 5 — the AI taste layer:** let Claude _choose_ which of the now-built moves to make (from the same legal set the rules produce), instead of fixed rules. Read the recipe: [house-bollywood-recipe.md](house-bollywood-recipe.md).
4. **Clear the open R1 safety item before ANY merge to main** (see Open escalations) — still owed.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at this handoff** (with the in-flight vocal-chops code present): `services/api` → `.venv/Scripts/python -m pytest -q` → **293 passed in ~26s**. Root → `npm test` → **7 files, 39 passed**. Root → `npm run typecheck` → **clean (tsc --noEmit, no errors)**.
- **The four beat moves** were each verified end-to-end (no cloud cost) on the real Father Ocean × Der Lagi pair every iteration: `validate_plan`/`validate_render` CLEAN, no clip; specific measurements in the drift log (e.g. breakdown 5:42–5:58 bass 0.14→0.023 then returning, return click-free at 0.72× typical motion; a full-track silence sweep found nothing but the song's natural ending). **These four are safe-surface (fence/plan only) — `render.py`/`validate.py` confirmed unchanged for them via `git diff --stat`.**
- **Vocal chops (IN FLIGHT):** MY checks only — no-chop render byte-identical (max diff 0.0) to the field-absent plan; chopped bar shows 8 rhythmic onsets; real pair `validate_plan`/`validate_render` CLEAN, peak 0.891, no clip. **The independent test-author + adversarial review did NOT return — this is the claim that must be re-verified.**

## Open escalations

- **⚠️ RE-VERIFY BEFORE TRUST/MERGE (a CLAIM, not settled): the vocal-chops `render.py` change has NOT had its independent safety review.** Committed in flight (`a405ad8`) with a flag. Complete the test-author + adversarial pass (do-first #1) before relying on it.
- **⚠️ RE-VERIFY BEFORE MERGE (carried forward, unchanged): the pre-existing R1 relaxation is still NOT cleanly adversarially cleared.** To allow the natural vocal hand-off, `validate.py` R1 was loosened to permit a bounded overlap (Song 1's tail may run ≤ `LEAD_XFADE_SECS`=1.2s past Song 2's entry) WITHOUT an engine-guaranteed fade. A fresh adversarial pass on the bounded-no-fade relaxation MUST run before `feat/house-bollywood-energy-sync` merges to main. Not touched this session.
- **Branch not merged; `main` is behind.** Merge deferred by the founder. Merging needs: the two re-verifies above, and lock CORS in `config.py` to the real origin if deploying.
- **Catalog + cached analyses live only in gitignored `data/`** (not reproducible from git). A fresh machine must re-ingest and **split-before-analyze** (the trap that causes empty vocal_regions → short mid-word vocals).
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do not make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live.
**Founder ear-test loop (what worked all session, no cloud cost):** render a WAV of the real pair via the deterministic pipeline (`os.environ.pop("ANTHROPIC_API_KEY")` forces the free rules path; `build_mix_plan` → `render_mix`) and open it from the Desktop under a **fresh, distinct filename** (same-name overwrites get served from the OS/OneDrive cache). Bump `ENGINE_VERSION` in `routes/mix.py` on each engine/plan change (now at **`m5n.0`**).
