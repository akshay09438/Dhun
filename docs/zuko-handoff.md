# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-06 (M3 session - the first real mix built, heard live, and fixed)

## Where things stand (one breath)

**M3 is built and the app made its first real mix.** Upload two songs → clean & playable (M1) → split into vocals/drums/bass/other (M2a) → analyzed like a DJ: BPM, key, structure, energy, vocal map (M2b) → **now: "Make my mix" produces Song 1's beat + Song 2's vocal, tempo-locked and dropped on the strongest section, playable and downloadable (M3).** The founder heard a genuine merge on a compatible pair this session - the milestone moment. Two independent reviews (scalability + adversarial safety) ran; their fixes are applied. **74 tests green** (65 backend + 9 web). All on branch `feat/m3-mix`.

## In flight

- **One thing pending: the post-fix re-listen.** The founder's first live mix had a ~2-second silent "pause" right before the vocal (the AI's "beat-breath" rendered as one bar of dead air). **This was fixed this session** (beat now plays continuously; `ENGINE_VERSION` bumped so the gappy cached mix isn't re-served) and committed, but the founder had **not yet re-listened to the fixed version** when the session closed. **This is the open M3 acceptance step.**
- **Working tree clean**; M3 + the gap fix are committed (`d52d812`, `b44b62f`). Suite green (evidence below).
- **Servers left running** for the re-listen: backend on :8000 (fresh, running the fix) and web on :5173. App URL: http://localhost:5173.
- **No GitHub remote** - work lives on local branch `feat/m3-mix`; no PR could be opened. Offer to set up a remote next session (for PRs + backup).

## Do first next session

1. **Re-listen to the fixed mix** (the pending M3 acceptance). Best pair (verified compatible): **Father Ocean (Song 1, beat - 122 BPM, 10B) + Dua Lipa "Don't Start Now" (Song 2, vocal - 124 BPM, 10A)** - ~1.6% tempo apart and a perfect relative-key match. Flow: refresh http://localhost:5173 → re-upload the two songs (analysis/stems are cached, so instant) → Make my mix. Judge it on: the ~2s gap is gone, beat runs continuously under the vocal, entry is on-beat and click-free. If a residual **vocal-vs-beat drift** over the long placement is audible, that's the next thing to chase (partly an M4 phase-lock job).
2. **If the re-listen is clean → M3 is done.** Then start **M4 (full DJ arrangement + regenerate)**: the vocal weaving in/out (≥2 placements), a _real_ beat-breath (tension/bass-cut, not silence), keep-S1-vocal for contrast, FX, confidence fallbacks, and the "give me another take" button. This is where the app stops feeling sparse.
3. Consider connecting a **GitHub remote** and opening PRs for the M3 work.

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-06:

- Backend: `pytest -q` in `services/api` → **65 passed** (was 26 pre-M3; +39 for fence/plan/validate/render/mix-route + hardening + the gap fix). Includes a real end-to-end render through FFmpeg on synthetic songs.
- Web: `npm run typecheck` → **PASS** · `npm run lint` → **PASS** · `npm test` (vitest) → **9 passed** (3 files).
- **Live, real songs this session:** the app produced and played a genuine mix on a compatible pair (the merge sounded good). Surfaced one real bug (~2s dead-air gap) - **fixed and committed**; the fixed version is **not yet re-listened** (see In flight). The ±8% tempo guard correctly declined mismatched pairs (Father Ocean 122 vs Tere Bina 143 → ~15%; vs Sahiba 100 → ~22%) with plain-language reasons - working as designed.

## Open escalations

- **None blocking.** No red suite, no work waiting on a human decision.
- **CLAIMS to re-verify (not settled facts):**
  - The two dangerous-surface files (`workers/render.py`, `services/api/app/planner/validate.py`) were created and later **hardened** this session (near-silence guard; decoded-duration cap; tempo/anchor guards) via the confirm-and-apply flow with the founder's explicit approval; approval was cleared afterward. An adversarial review returned **not-proven-safe** on two "should-fix" gaps, both now hardened - **re-verify next session that those guards actually hold** (a near-silent render is rejected; a tiny-but-hours-long file can't balloon memory) rather than trusting this sentence.
  - The M1 "before any public exposure" items **remain open** and gate any public launch: sandbox/resource-limit FFmpeg on untrusted input, proxy-level rate/body limits, HTTP-level traversal + oversize tests. Add a **duration cap at upload** (M3 only caps at render).
- **M4 / scaling backlog (logged, deliberate - not needed at validation scale):** mix-WAV cache has no eviction (fastest-growing data; worse once regenerate lands); extend `MixPlan` **additively** for M4's multiple placements so cached plan JSON still parses; extract the async-job skeleton (now duplicated in stems/analysis/mix); in-memory `_jobs` + local-disk readiness break at the first multi-worker deploy / object-storage move.
- **Keys / cost:** `REPLICATE_API_TOKEN` + `ANTHROPIC_API_KEY` in the gitignored root `.env`. This session spent Replicate credit analyzing/splitting new songs (Tere Bina, Sahiba, and the compatible vocal) - **check remaining credit** before a heavy next session. Anthropic (`claude-sonnet-5`) powers the mix planner; cost is negligible (tiny structured calls) and it falls back to rules if the key/network is absent.
- **Environment truths (unchanged, hard-won):** PyTorch/librosa/madmom cannot run on this Windows-ARM machine - heavy audio goes through Replicate; local DSP is FFmpeg + numpy/scipy only. Time-stretch is **FFmpeg `atempo`** (LGPL, already installed) - do not add GPL rubberband to the pipeline. Watch disk as cached stems/mixes accumulate.

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Or the `.claude/launch.json` configs (backend + web). Both are currently running.
