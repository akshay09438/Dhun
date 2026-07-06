# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-06 (big session — M4 finished + live-confirmed, GitHub backup set up, M5 Slice 1 built + confirmed)

## Where things stand (one breath)

**V1 Feature 1 (the offline DJ mix) is DONE and founder-confirmed "perfect."** Upload two songs → clean & playable (M1) → stems (M2a) → analysis (M2b) → **"Make my mix" produces a full DJ arrangement**: Song 1's beat throughout, Song 2's vocal spread across the WHOLE song as an energy arc (not clustered), **re-locked to the beat every bar so it never drifts** (315 ms → 0 ms on the real 7:52 pair), Song 1's own vocal answering in a gap for contrast, one subtle sweep, Regenerate, and an arrangement timeline. **V1 Feature 2 (live steering) has STARTED — M5 Slice 1 is built and confirmed working:** the mix screen now has a **live player** where you press play and type **"take the bass out" / "bring it back"** and Song 1's bass drops/returns **on the beat** with a smooth 1-bar fade, replying in DJ language. All on branch `feat/m5-live-control`, **also backed up to GitHub** (new this session). **154 tests green (136 backend + 18 web).**

## In flight

- **Nothing half-done.** Working tree clean (only the gitignored `.superpowers/sdd/` SDD ledger is untracked). Every piece committed on `feat/m5-live-control`. Suite green (evidence below).
- **No open acceptance** — the founder live-confirmed both the full M4 mix AND the M5 Slice 1 "take the bass out" this session.
- **Servers left running** on Slice 1 code: backend :8000 (now includes `/live/command` + `/live/context`), web :5173 → http://localhost:5173.
- **GitHub remote is now set up** (`origin` → https://github.com/akshay09438/Dhun): all local branches + `main` pushed for backup. No secrets/`data/` uploaded (gitignored, verified). **No PR flow in use yet** — branches pushed as backup only; `main` == the confirmed M4 tip.

## Do first next session

1. **Build M5 Slice 2 — "the full mix, live, all parts controllable"** (scope CONFIRMED by the founder). Two things: (a) layer **Song 2's arranged vocal** into the live player so you hear the _real_ mix, not just Song 1's groove; (b) make **every part** (bass / vocals / drums / "drop everything but the beat") mute/unmute-able on the beat. **KEY DESIGN (decided):** do NOT rebuild the M4 arrangement in the browser — have the backend export an **"arranged Song-2 vocal" bus** (silence except where the M4 plan places it, with the warp+fades+contrast already baked by the trusted render engine), which the browser plays alongside Song 1's stems from t=0 and mutes/unmutes live. **Reuse `workers/render.py`'s helpers in a NEW module `workers/live_stems.py` if possible; if it must edit `render.py`/`validate.py`, that's the confirm-and-apply heavy path.** It's a meaty architectural piece → brainstorm → plan → build like Slice 1. (The design + plan for Slice 1 are the template: `docs/superpowers/specs|plans/2026-07-06-m5-slice1-*`.)
2. **Then M5 Slice 3 — the AI smart-buttons** (the founder's favorite): the AI decides how far to pull a part AND surfaces 1–3 **context-aware suggestion buttons that change as the song plays** (point the arrangement judgment brain at the live playhead; pre-compute per-section suggestions, don't call the AI every beat). Then the remaining energy moves ("beat up", "fade away").
3. **Before the ~50-user test:** the **mix-WAV cache eviction** sweep (top backlog item; Regenerate writes ~40–80 MB WAVs, nothing deletes them; belongs in `storage.py`, a **dangerous** surface, so gate it), plus the one-click **"Studying your songs"** screen (auto split+analyze).
4. **M6:** loudness master (limiter) + short-clip (15–30s) export + the ~50-creator validation test.

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-06:

- Backend: `pytest -q` in `services/api` → **136 passed** (was 91 pre-session; M4 Slice C/D added arc + beat-lock + R7 tests, M5 added live parser/route tests).
- Web: `npm run typecheck` → **PASS** · `npm run lint` → **PASS** · `npm test` (vitest) → **18 passed** (5 files) (was 10; M5 added api/liveSchedule/LiveMix tests).
- **M4 verified end-to-end this session (no cloud cost, real cached 122-BPM 7:52 + 125-BPM pair):** energy arc spans first-half→final-third (Take 1 vocal at 1:52/5:01/5:32, Take 2 at 1:36/4:29/6:51, takes differ); per-bar beat-lock drift **315/236/180 ms → 0/0/0 ms**; R7+R1+R6 referees pass; valid render.
- **M5 Slice 1 live route verified live:** `POST /live/command "take the bass out"` → `{op:"mute",target:"bass",say:"dropping the bass on the next bar"}`.
- **Reviews this session:** M4 Slice C shipped (arc). M4 Slice D (beat-lock) — independent test-author + 3-lens quorum; safety lens caught a real must-fix (R7 falsely rejected ~29% of mid-bar-start plans), **fixed** (warp starts on a downbeat; glitch→legacy) and **re-reviewed SAFE** (29%→0.2% loud declines, 0 overlaps). M5 Slice 1 — subagent-driven TDD (6 tasks) + a whole-branch review that found one must-fix (a backend test wrote to the real `data/` dir and flaked `test_analysis_route`) — **fixed** (`tmp_path` isolation) + verified clean.

## Open escalations

- **None blocking.** No red suite, no work waiting on a human decision.
- **CLAIMS to re-verify (not settled facts):**
  - The dangerous-surface changes this session — `workers/render.py` + `services/api/app/planner/validate.py` (M4d beat-lock) — were built via confirm-and-apply (founder approval recorded + cleared) and reviewed **SAFE**. The web `*.test.ts`/`*.test.tsx` files (dangerous test-harness surface) got new tests via confirm-and-apply too (founder approved; cleared). **Re-run the full suite next session** before building on any of it; the safe verdicts were on the diff as reviewed.
  - **M4d logged residual (low, loud, non-blocking):** ~0.2% of band-edge pairs get a _loud_ R7 decline (a rounding mismatch on a trailing-partial bar) — user just regenerates; never a silent bad mix. Fix when next in `validate.py`: give R7 a rounding-aware tolerance.
  - **M5 minors (non-blocking):** the live parser is stateless so "bring it back" replies even if the bass was never gone; `liveAudio.schedule()` snapshots the instantaneous gain on rapid consecutive commands (inaudible for one-command-at-a-time). Both logged, safe for Slice 1.
- **M1 "before any public exposure" items still open** and gate a public launch: sandbox/resource-limit FFmpeg on untrusted input, proxy rate/body limits, HTTP traversal/oversize tests, a duration cap at upload.
- **Backlog (logged, deliberate — not blockers at validation scale):** mix-WAV cache eviction (top item before the user test); the M5 perf follow-up (per-bar render spawns ~60 FFmpeg calls — collapse to one filtergraph, bundle with eviction); `_ai_arrange` slice-start snap; async-job skeleton triplicated (now quadrupled with `/live`); in-memory `_jobs` breaks at multi-worker.
- **Keys / cost:** `REPLICATE_API_TOKEN` + `ANTHROPIC_API_KEY` in the gitignored root `.env`. Check remaining Replicate credit before a session that splits/analyzes NEW songs (the cached demo pair needs neither). Anthropic powers the arrangement + (future) live planner; falls back to deterministic rules if absent.
- **Environment truths (unchanged):** PyTorch/librosa/madmom can't run on this Windows-ARM machine — heavy audio via Replicate; local DSP is FFmpeg + numpy/scipy only. The live player uses the **raw Web Audio API** (Tone.js/wavesurfer named in the stack table are NOT installed — not needed).

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Or the `.claude/launch.json` configs (`backend`, `web`). Both are currently running on the Slice 1 code. The live player appears on the mix screen once both songs are uploaded; Song 1 must be split for it to load.
