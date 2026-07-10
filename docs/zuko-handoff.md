# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-09 (**GOOD-PARTS WINDOW DISABLED — mixes are FULL-SONG again (founder decision, ear-confirmed). Safe surface only: `plan.py` flag `_GOOD_PARTS_WINDOW_ENABLED=False`; `render.py`/`validate.py` UNTOUCHED. Committed + pushed (`1819072`). Also this session: built an isolated EXPERIMENT SANDBOX at `C:\DJ-AI-Experiment`, and wrote a full backend walkthrough doc. Suite green: 332 backend + 39 web, typecheck clean — re-run fresh at handoff.**) All work remains on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main**.

## Where things stand (one breath)

The founder chose **full-song mixes over the ~90s good-parts window**. Prototyped the change in the new sandbox first, the founder ear-confirmed the 4 full-song renders, then it was ported to main: `build_mix_plan` now gates the window on `_GOOD_PARTS_WINDOW_ENABLED = False`, so `window_span` is always `None` and every mix arranges across the whole track. The window machinery (`window.py` + the render/validate window-handling) is **kept dormant + tested** (one-line re-enable), matching the parked-vocal-chop convention — so `render.py`/`validate.py` never had to be touched. The still-open **#1 product decision from last handoff stands: the app should probably DEFAULT to the RULES arrangement path, not the AI path** (the AI arrangement is the one the founder dislikes).

## In flight — done vs left

- **Nothing is half-built or red.** The window-disable is committed + pushed (`1819072`), suite green.
- **Good-parts window: DONE (disabled).** Flag off; full-song mixes; tests updated (`..._uses_the_full_song`, `..._spans_the_full_song`; the validate windowed-plan test flips the flag on to keep the referee's window path covered). Living docs updated (functional-spec, technical-spec, mix-recipe, backend-explained, implementation-plan drift log #26).
- **Experiment sandbox: DONE.** A lean (1.7 GB) fully-working, **isolated** copy of the project at `C:\DJ-AI-Experiment` (own data folder, no git link to the real repo, off OneDrive), with a Desktop shortcut "DJ-AI-Experiment (sandbox)". Has all 28 songs' cached stems + analyses (re-render free), the venv, and the keys. It excludes the 5 GB of regenerable big WAVs. Verified: 332 tests pass inside it. **The sandbox's `plan.py` is synced to the same window-off flag as main.** Use it for any risky experiment, then "copy back" what works.
- **Backend walkthrough doc: DONE.** `docs/reference/backend-explained.md` — a plain-but-complete end-to-end explanation of the engine (for a technical helper), with a ranked "where to improve" section.
- **Phrasing:** confirmed already fully removed (reverted in a prior session; re-verified this session — no action needed).
- **Carried forward, UNCHANGED:** variation-in-app (first play fresh + keep/lock button); the set-builder API+screen (the shipped `set_render.py` is still a plain crossfade, no beatmatch); loudness master + short-clip export (M6).

## Do first next session

1. **⭐ Product decision (still #1): should the app DEFAULT to the RULES arrangement path?** The app uses the AI arrangement whenever `ANTHROPIC_API_KEY` is set, and that is the arrangement the founder consistently dislikes (the loved mixes are all rules-path; proven by sample-correlation last session). Options: default to rules; fix the AI path; or a toggle.
2. Whatever the founder wants to try next — **do it in the sandbox first** (that's what it's for), confirm by ear, then port to main.
3. The carried-forward roadmap: variation-in-app → set-builder → mastering/clip-export → the ~50-creator test.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **332 passed** (~52 s). Root → `npm run typecheck` → **clean (tsc --noEmit)**. Root → `npm test` → **39 passed (7 files)**.
- **Window-off proven on the real engine:** `build_mix_plan` on Father Ocean × Tere Bina (rules path) → `window = None`, 3 placements across the full **472 s** track.
- **Sandbox proven working + isolated:** 332 tests pass inside `C:\DJ-AI-Experiment`; its `settings.data_dir` resolves to its OWN folder (isolation confirmed); no `.git` (no link to the real repo).
- **Founder ear-confirmed** the 4 full-song sandbox renders before the main-folder change.
- `git` clean after commit `1819072`; pushed to `origin/feat/house-bollywood-energy-sync`.

## Open escalations

- **⭐ PRODUCT DECISION (founder): default the app to the RULES arrangement path** (see Do-first #1).
- **ℹ️ Good-parts window is now DISABLED (dormant flag).** Anyone expecting ~90s "best-part" mixes should know: it's off by default; re-enable = flip `_GOOD_PARTS_WINDOW_ENABLED` to `True` in `plan.py`.
- **⚠️ Pre-existing, carried forward, UNCHANGED (block merge to main):** (a) the R1 relaxation in `validate.py` (Song-1 tail ≤ `LEAD_XFADE_SECS` overlap) still NOT cleanly adversarially cleared; (b) lock **CORS** in `config.py` to the real origin before deploy. Also re-verify (claims, not facts) the earlier good-parts dangerous-surface edits before merge — though the window being OFF now means `render.py`/`validate.py` run their pre-window paths.
- **Branch NOT merged to main; `gh` CLI NOT installed here.** PR via web: https://github.com/akshay09438/Dhun/compare/main...feat/house-bollywood-energy-sync?expand=1

## Reference — sandbox, song id map, how to run

- **Experiment sandbox:** `C:\DJ-AI-Experiment` (Desktop shortcut "DJ-AI-Experiment (sandbox)"). Fully isolated, off OneDrive. Run its engine with `C:\DJ-AI-Experiment\services\api\.venv\Scripts\python.exe`. Do risky experiments here; copy back what works.
- **song_id = sha256 of the normalized WAV.** Cached ids: Anchor Point=`2c17fc64`, Father Ocean=`ac59f8c4`, Innerbloom=`2471e18e`, Dooriyan=`c4b28366`, Maula Mere=`6608cb48`, Der Lagi=`bbab7b9f`, Don't Start Now=`c0c6ab91`, Tere Bina=`6ad69035`, Jee Karda=`2294a715`, Dil Ye Bekarar=`73431441`, Tujhe Bhula Diya=`fedc95c9`, I Adore You=`b8696c4d`, Rapture=`7f0b66c9`, How Deep Is Your Love=`4e246293`.
- **Data cache** at `services/api/data/` (gitignored) — stems + analyses cached, re-renders FREE. Big source/output WAVs (~5 GB) are regenerable and NOT in the sandbox.
- **Founder ear-test loop (no cloud cost):** **pop `ANTHROPIC_API_KEY`** → forces the **RULES path, the arrangement the founder likes** (the AI path arranges differently). Then `build_mix_plan(a1, a2, take=N)` → `render_mix(plan, {drums/bass/other/vocals}, song2_vocal, out)`. Analysis JSON in `data/` lacks the `status` field — inject `status="ready"` when loading via `TrackAnalysis.model_validate`.
- **Where mixes are saved:** `C:\Users\Akshay\OneDrive\Desktop\DJAI SONGS`. Fresh distinct filenames (same-name can serve from the OS/OneDrive cache). **Windows gotcha:** no `>` in filenames.
- **Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (root), open http://localhost:5173.
