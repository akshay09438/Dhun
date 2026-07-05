# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-05 (end of the marathon founding session)

## Where things stand (one breath)

From an empty folder to a working app in one day: upload two songs → cleaned & playable (M1 ✅) → split into vocals/drums/bass/other via cloud AI (M2a ✅, incl. an async fix for long songs) → analyzed like a DJ reads a track: BPM, key, structure, energy, vocal map (M2b ✅). All committed on branch `feat/m2-stems`. **Next: M3 — the first real mix.**

## In flight

- **Nothing half-done.** Working tree clean; all of M1/M2a/M2b committed. Suite green (evidence below).
- Branch state: `main` holds only the bootstrap; the work sits in sequence on `setup/zuko-bootstrap` → `feat/m1-upload-skeleton` → `feat/m2-stems`. **No GitHub remote yet** — no PRs exist; work lives in local branches.

## Do first next session

1. Run `/zuko:start` to orient, then **`/zuko:build` for M3 — the basic mix**: Song 1's instrumental bed + Song 2's vocal, tempo-locked (SoundTouch enters here), phrase-aligned, vocal placed on a high-energy section; export WAV. This is the product's first "whoa" and where `docs/reference/DJ-Judgment-Handbook.md` starts being implemented (the `ANTHROPIC_API_KEY` already in `.env` powers the MixPlan planner).
2. Consider connecting a GitHub remote and merging the three work branches into `main` (or via PRs once a remote exists).

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-05 ~23:00:

- Backend: `pytest -q` in `services/api` → **26 passed in 2.70s**.
- Web: `tsc --noEmit` → clean · `vitest run` → **7 passed** · `eslint src` → exit 0.
- Live end-to-end checks performed this session (real cloud calls, real songs):
  - Upload round-trip: mp3+wav in → 44.1kHz stereo WAV out (verified via HTTP + ffprobe).
  - Stem split: Father Ocean (7:56 — the song that exposed the timeout bug) → POST returned in 1s (202 processing), READY after ~90s, vocals stem served (19MB).
  - Analysis: Father Ocean → **bpm 122 (correct)**, key D major/10B (conf 0.7), 925 beats / 232 downbeats / 29 phrases, full section map, 11 vocal regions (conf 0.8).

## Open escalations

- **None waiting on a human.** No red suite, no blocked work.
- CLAIMS to re-verify (not settled facts): the dangerous-surface upload/storage/config files were cleared by one adversarial review (M1) with both must-fix items applied (ffmpeg timeout; streaming size cap). Its **"before any public exposure"** items remain open and gate any public launch: sandbox/resource-limit ffmpeg on untrusted input, proxy-level rate/body limits, HTTP-level traversal + oversize tests.
- **Keys:** `REPLICATE_API_TOKEN` and `ANTHROPIC_API_KEY` live in the gitignored root `.env` (never committed). Replicate has ~$5 credit; a new song costs ~2–6¢ to split + ~1–2¢ to analyze, cached forever after (re-use is free).
- **Environment truths (hard-won):** PyTorch / librosa / madmom / essentia **cannot run** on this Windows-ARM machine — audio-AI goes through Replicate; local DSP is FFmpeg + pure numpy/scipy only. WSL was removed (with founder consent) to reclaim ~12GB after the failed local-AI attempts — do not reintroduce it. Disk hit 0 bytes free mid-session; ~13GB free after cleanup — **watch disk** as cached stems accumulate.

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Or the `.claude/launch.json` configs (backend + web).
