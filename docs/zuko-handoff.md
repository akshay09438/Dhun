# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-06 (M4 session - full DJ arrangement built end to end)

## Where things stand (one breath)

Upload two songs → clean & playable (M1) → split into stems (M2a) → analyzed like a DJ (M2b) → **"Make my mix" now produces a full DJ arrangement:** Song 1's beat throughout, Song 2's vocal weaving in/out across several sections, a real one-bar beat-breath and one subtle filter sweep into a big entry, **Song 1's own vocal answering in a gap for contrast** (the two songs trade, never two voices at once), auto-simplified on shaky songs — with a **Regenerate** button and an arrangement timeline that shows both voices. **M3 is done and live-confirmed. M4 is complete in code** (Slice A live-confirmed by the founder; Slice B built + independently reviewed **SAFE** + verified on a real render). **101 tests green** (91 backend + 10 web). All on branch `feat/m4-arrangement`.

## In flight

- **Nothing half-done.** Working tree clean; every M4 piece committed on `feat/m4-arrangement`. Suite green (evidence below).
- **The one open item is a human LISTEN, not code.** The full M4 (contrast + sweep) has **not been ear-checked by the founder yet** — automated checks and the adversarial review confirm it's _safe and structurally correct_, but whether the contrast and the sweep _sound good_ (any faint click? contrast balance?) is the one thing CI can't judge. The safety reviewer explicitly recommended a human listen to one real contrast+sweep mix. **This is the open M4 acceptance step.**
- **Servers left running** on M4b code: backend :8000, web :5173 → http://localhost:5173.
- **No GitHub remote** - work lives on local branches (`feat/m3-mix`, `feat/m4-arrangement`); no PRs. Offer to set up a remote next session (backup + PRs).

## Do first next session

1. **Live-listen the full M4** (the open acceptance). App is running M4b; make a mix from a compatible pair (the cached **122-BPM beat + 125-BPM vocal** works, or Father Ocean + Dua Lipa "Don't Start Now"). Judge: does Song 1's voice answering in a gap feel like a cool _trade_; is the sweep a nice build **with no click** at its start; does it feel richer than Slice A; does Regenerate give a genuinely different take. If good → **M4 fully done**.
2. **Then land the mix-WAV cache eviction sweep** — the top backlog item, **before the ~50-user test**: Regenerate saves a new ~40 MB WAV per take and nothing deletes them (disk hit 0 once before). A keep-newest-N / age sweep over `data/*.mix.wav` (deletes finished mixes → belongs in `storage.py`, a **dangerous** surface, so gate it). In-process/local only; no Redis/Postgres.
3. **Then M5** (lean live commands) - or M6 polish (loudness master + short-clip export) per priority.

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-06:

- Backend: `pytest -q` in `services/api` → **91 passed** (was 26 pre-M3; M3 + M4a + M4b added the fence/planner/validate/render/mix-route suites incl. real-FFmpeg renders and the two-voices-overlap guards).
- Web: `npm run typecheck` → **PASS** · `npm run lint` → **PASS** · `npm test` (vitest) → **10 passed** (3 files).
- **Real end-to-end render this session (no cloud cost, cached pair 122+125 BPM, stretch 0.976 — the fixed sub-unity case):** a full Slice B arrangement — S2 vocal at 0:18 / 0:33 / 0:49 (sweep on the 0:49 entry), **Song 1's own vocal answering at 2:41 for contrast**, **S1/S2 NO-OVERLAP verified**, valid 7:56 stereo WAV (peak 0.891, audible 0.88). Both independent reviews on M4a and M4b ran; the M4a safety review **caught a real overlap bug (inverted atempo math), fixed same session**; the M4b safety review returned **SAFE**.

## Open escalations

- **None blocking.** No red suite, no work waiting on a human decision (only the optional live listen).
- **CLAIMS to re-verify (not settled facts):**
  - The M4 dangerous-surface guards (`workers/render.py`, `services/api/app/planner/validate.py`) were built + hardened via confirm-and-apply with founder approval; approvals cleared. Adversarial review verdict **SAFE** (two-lead-voices guarantee held under attack). **Re-verify next session by ear** that a real contrast+sweep mix has no click and the contrast sits right - that is the one dimension code review couldn't cover.
  - M1 "before any public exposure" items **remain open** and gate a public launch: sandbox/resource-limit FFmpeg on untrusted input, proxy rate/body limits, HTTP traversal/oversize tests, and a **duration cap at upload** (render caps at 12 min; upload only caps bytes).
- **Backlog (logged, deliberate - not blockers at validation scale):** (a) **mix-WAV cache eviction = top item before the user test** (see Do-first #2). (b) async-job skeleton triplicated (stems/analysis/mix) - extract one helper on next touch. (c) in-memory `_jobs` + local-disk readiness break at first multi-worker deploy / object-storage move. (d) `bpm_confidence is None` defaults to "confident" (only reachable on legacy analyses; real pipeline always sets it) - consider defaulting unknown→shaky. (e) `Placement.fx` is a bare string (deliberate, referee typo-guards it); if `s1_vocal_regions` ever grows a per-region field, promote the tuple to a named model in the same change.
- **Keys / cost:** `REPLICATE_API_TOKEN` + `ANTHROPIC_API_KEY` in the gitignored root `.env`. **Check remaining Replicate credit** before a session that splits/analyzes new songs. Anthropic (`claude-sonnet-5`) powers the arrangement planner; negligible cost and it falls back to deterministic rules if the key/network is absent (the deterministic fallback is what the real renders above used).
- **Environment truths (unchanged):** PyTorch/librosa/madmom can't run on this Windows-ARM machine - heavy audio via Replicate; local DSP is FFmpeg + numpy/scipy only. Time-stretch is FFmpeg `atempo` (LGPL); the sweep uses `scipy.signal`. Watch disk as cached stems/mixes accumulate (see backlog a).

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Or the `.claude/launch.json` configs. Both are currently running on the M4b code.
