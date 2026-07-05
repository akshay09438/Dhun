# Prompt-DJ — Implementation Plan

_How far along we are, what's in flight, what's left, and the drift log. Living document — updated at each milestone and at `/zuko:handoff`._

## Status: **M1, M2a, and M2b complete — 33 tests passing, analysis live-verified (Father Ocean read at 122 BPM, correct).** Next: M3 (the first real mix).

Demand is founder-validated, so we skipped the hand-made validation gate (former "M0"); the first real proof point is **M3** — the first genuinely good mix.

**M2 was split into M2a (stem separation) and M2b (analysis), stems first.** The heavy audio-AI runs in the cloud (Replicate), because PyTorch cannot run on the founder's Windows-ARM machine (proven — see [cloud-and-cost-plan.md](cloud-and-cost-plan.md)).

## Milestones

| #   | Milestone           | Goal                                                                                                                        | Acceptance                                                                   | Status  |
| --- | ------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------- |
| M1  | Skeleton            | Two-file upload → normalized WAV, stored; app runs end to end                                                               | Upload two songs, get them back re-encoded                                   | ✅ Done |
| M2a | Stem splitting      | Split each song into vocals/drums/bass/other (Replicate Demucs), cached; play each part in the app                          | Isolated vocal intelligible; cached so each song splits once                 | ✅ Done |
| M2b | Analysis            | `TrackAnalysis` (BPM/beat/downbeats/key/sections/energy/vocal-regions) with per-field confidence, cached; overlays in UI    | BPM ±1 and downbeats on the one for demo pairs                               | ✅ Done |
| M3  | Basic mix           | Song 1 bed + Song 2 vocal placed on the drop, tempo-locked, phrase-aligned; export WAV                                      | Drift-free, on-phrase, click-free, single vocal — **the first "whoa"**       | ☐       |
| M4  | Full DJ arrangement | Judgment layer: varied placement, beat-drop breaths, keep-S1-vocal, ≥2 placements, FX, confidence fallbacks, **regenerate** | Success criteria S1–S4 on demo set; regenerate yields a different valid plan | ☐       |
| M5  | Lean live control   | Stem-bus player + on-beat scheduling; the lean command set; orchestration; out-of-scope decline                             | Every command lands on the beat, no artifact/stall                           | ☐       |
| M6  | Polish + share      | Loudness/limiter; short-clip export; the ~50-user test                                                                      | Clean master; ~50 creators feel the magic                                    | ☐       |

## Deltas from the original PRD (decided during discovery, 2026-07-05)

- One target user (casual creators), not three.
- Feature 2 leaner + Regenerate promoted to first-class.
- Short-clip (15–30s) export added as a hero output.
- Live BPM change explicitly deferred to V2.
- Right-sized stack: SQLite + local storage + in-process jobs for validation (audio toolchain unchanged).
- Time-stretch: SoundTouch (free) by choice, swappable to Rubber Band.

## Curated demo pairs (to assemble before/with M3)

~10 pairs: mostly _compatible_ (close BPM, Camelot-adjacent, clear structure) to showcase quality; 2–3 _hard_ pairs to exercise fallbacks. Hand-verify grid/key/sections. Include a couple of Indian pairs, hand-checked (weaker analysis there).

## Drift log

_(record any place the docs and code diverge, and how it was resolved)_

- 2026-07-05 — Repo bootstrapped from discovery. No code yet; specs are intended design, not as-built.
- 2026-07-05 — **M1 complete.** Minor deviations from the plan, all harmless: `uvicorn` (not `uvicorn[standard]`) because `httptools` has no prebuilt wheel for Windows/ARM64; pytest config lives in `pyproject.toml` (not a guarded `pytest.ini`); corrected the danger-glob paths to the real `services/api/**` layout so the upload handler is actually guarded; two security hardenings from the adversarial review folded in (FFmpeg timeout; streaming upload size-cap). No DB/queue in M1 (as planned). Live HTTP round-trip verified: mp3+wav in → 44.1k stereo WAV out.
- 2026-07-05 — **Follow-up for M2+:** CI's coverage job expects `coverage/coverage-summary.json` at repo root, but web coverage writes to `apps/web/coverage/`; and CI has no Python (pytest) job yet. Wire both when a GitHub remote is added.
- 2026-07-05 — **Big architecture pivot in M2a:** the heavy audio-AI (Demucs, PyTorch) **cannot run on the founder's Windows-ARM machine** — PyTorch crashes on import (Bus error), confirmed after a thorough WSL attempt (which also destabilized WSL). So stem separation runs in the **cloud via Replicate** (`ryan5453/demucs`, htdemucs). API keys live in a gitignored root `.env`, loaded at startup. Results cached by content id → each song splits once. This confirms the buy-not-built map: the local machine is dev-only; real users will always need cloud audio. M2b analysis will follow the same cloud pattern.
- 2026-07-05 — **M2a complete.** Backend: `app/audio/stems.py` + `app/routes/stems.py` (split + serve, hex-id validated), `StemSet` model, 7 tests (download/store, cache-hit-no-call, error wrap, route validation). Front end: per-song "Split into parts" → 4 stem players, +1 test. Live end-to-end verified through the running server (upload → split → isolated vocals returned). 23 tests total.
- 2026-07-05 — **M2b complete.** Cloud: Replicate `sakemin/all-in-one-music-structure-analyzer` (allin1) → BPM, beats, downbeats, sections. Local pure-numpy (librosa/madmom don't install on ARM Windows — numba/llvmlite have no wheels): key via chromagram + Krumhansl–Kessler → Camelot; energy = RMS/bar; vocal regions from the split vocal stem; phrase starts = every 8th downbeat; confidence on every field (beat-regularity for bpm, profile margin for key, fixed 0.6 for sections — the weak link). Async start-then-poll route, cached JSON per song. UI: "Analyze track" → BPM chip, Camelot chip, proportional section timeline. Live verify: Father Ocean read at **122 BPM (correct)**, D major 10B (conf 0.7, honestly flagged), full structure map, 11 vocal regions. 33 tests total.
- 2026-07-05 — **Ops note:** C: drive hit 0 bytes free mid-M2b (the WSL Ubuntu vhdx had ballooned to 11.8 GB from the failed PyTorch attempts). With the founder's explicit consent, the unused Ubuntu WSL distro was removed (~12 GB reclaimed); pip caches and scratch clips cleared. WSL is no longer part of this project (cloud pivot).
- 2026-07-05 — **Bug fix (M2a): long songs failed to split.** Root cause: splitting held one HTTP request open for the full ~2min cloud job, and long songs (7:56) exceeded the request timeout while short ones (5:08) squeaked under — a fragile synchronous design. Fixed by making it **asynchronous**: `POST /songs/{id}/stems` starts a background thread and returns `202 processing` at once; `GET /songs/{id}/stems` reports processing/ready/error; the web app polls. In-memory `_jobs` registry (fine for single-worker validation; a persisted job table when hosted). Reproducing test added (async contract). Verified live on Father Ocean: POST returns in 1s, ready after ~90s. This matches the PRD's original async-jobs intent, deferred in M1/M2a and now needed.
