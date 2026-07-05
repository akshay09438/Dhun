# Prompt-DJ — Technical Spec (V1)

_How it is built. Starts as the intended design (from the PRD + discovery deltas); becomes as-built as code lands. Living document — if code and this doc disagree, the code wins and this doc is corrected. Full background: [reference/PRD.md](reference/PRD.md)._

## The one architectural principle (do not violate)

**The language model plans. The audio engine executes. They never mix.** The LLM turns (analysis + request) into a structured `MixPlan` (Feature 1) or a `LiveOp` (Feature 2). A deterministic render/playback engine executes those objects with DSP. The LLM never touches audio samples. This buys: editability, near-zero LLM cost, no hallucinated audio, and full debuggability.

## Stack (right-sized for validation scale; audio toolchain kept best-in-class)

| Layer                | Choice                                                             | Notes                                                                                           |
| -------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| Frontend             | React + Vite + TypeScript, wavesurfer.js, Web Audio + Tone.js      | upload, arrangement view, stem-bus player, live prompt bar                                      |
| Backend              | Python 3.11 + FastAPI + Pydantic v2                                | Pydantic schemas = data source of truth                                                         |
| Jobs                 | **In-process background tasks** (not separate Redis + workers yet) | upgrade to Redis/RQ when past validation scale                                                  |
| DB                   | **SQLite** to start                                                | upgrade to Postgres when it grows; no audio-quality impact                                      |
| Storage              | **Local disk** (`data/`, gitignored) to start                      | upgrade to Cloudflare R2 / S3 later                                                             |
| Stems                | **AudioShake / Music.ai API** (or self-host Demucs on Modal later) | 🎯 quality-critical — best-in-class                                                             |
| Analysis (MIR)       | librosa + madmom + Essentia + allin1                               | BPM/beatgrid/downbeats/key/sections/energy/vocal regions                                        |
| Time-stretch / pitch | **SoundTouch (free)** for V1 by choice                             | kept swappable to Rubber Band (paid, better on big stretches) in one file; keep stretches small |
| Mux / encode         | FFmpeg (LGPL build) + numpy                                        |                                                                                                 |
| LLM                  | Anthropic Claude API (structured output)                           | `MixPlan` + `LiveOp` only                                                                       |

**Why simplified vs. the PRD:** the PRD pins Postgres + Redis + separate workers + object store for scale. For ~50 users we run a single FastAPI app + SQLite + local storage + in-process jobs. This is _plumbing only_ — it has zero effect on how the mix sounds, and each piece upgrades independently without touching the audio engine.

## Core data models (Pydantic — the source of truth)

`TrackAnalysis` (per song, cached by content hash) · `StemSet` (per song, cached) · `MixPlan` (Feature 1 spine: bed + topline + sync + arrangement[] + fx) · `LiveState` + `LiveOp` (Feature 2). See PRD §5 for full schemas.

## Feature 1 pipeline (stage by stage)

Ingest (FFmpeg normalize) → Analysis (cached, with per-field confidence) → Stem separation (cached) → Arrangement planning (Claude + deterministic helpers + validator) → Tempo lock (SoundTouch) → Key lock → Beat alignment → Render/mixdown (flat file + stems-preserved live bundle) → Post (loudness normalize + limiter). See PRD §6.

## The judgment layer (the moat)

Deterministic helpers the LLM calls (never guesses): `snap_to_phrase`, `camelot_fit`, `stretch_ratio`, `vocal_regions`, `section_windows`. The LLM picks taste among _legal_ options; a validator enforces the hard rules (R1 one vocal at a time, R2 one bassline, R3 boundaries on downbeats, R4 key-clash guard, R5 ≥2 distinct vocal placements, R6 no clipping). Full rulebook: [reference/DJ-Judgment-Handbook.md](reference/DJ-Judgment-Handbook.md) (Parts 1–8 craft, Part 9 confidence/fallback, Part 10 live orchestration).

## Feature 2 (live, lean)

Playback holds separately-addressable stem buses (`s1.drums, s1.bass, s1.other, s1.vocals, s2.vocals`). Commands become on-beat `LiveOp`s (energy/element moves only in V1). Scheduler uses Song 1's grid as the master clock (Tone.js Transport / server-authoritative to start). Two invariants: music never stops; nothing fires off-grid. **Live BPM change is out of V1** (V2 stretch goal).

## The dangerous 5% (mirrors `.zuko/config.json`)

Secrets/keys · the upload handler (untrusted input) · storage deletes (irreversible) · the render pipeline + quality validator · CI/test harness. No real auth or payments in V1.

## As-built (M1)

- `services/api/app/`: `config.py` (limits), `audio/normalize.py` (FFmpeg two-pass peak-normalize → 44.1k/stereo/16-bit, with a subprocess timeout), `storage.py` (content-hash save/serve, hex-id validation), `routes/songs.py` (streaming size-capped upload + serve), `main.py`. 10 pytest tests.
- `apps/web/`: React+Vite+TS upload screen (`components/Uploader`), `lib/api.ts` client. 5 vitest tests.
- Time-stretch not yet wired (arrives with mixing in M3); SoundTouch chosen for then.

## As-built (M2a — stem splitting)

- **Runs in the cloud, not locally.** PyTorch/Demucs can't run on the founder's Windows-ARM machine (proven), so separation calls **Replicate** (`ryan5453/demucs`, htdemucs) over HTTP. The `replicate` client is pure-Python and runs fine locally.
- `services/api/app/audio/stems.py`: `separate_stems(song_id, wav)` → 4 stems, **cached by content id** (no repeat API cost). `app/routes/stems.py`: `POST /songs/{id}/stems` (split), `GET /songs/{id}/stems/{stem}` (serve, id+stem validated). `StemSet` model. 7 tests (mocked Replicate).
- `apps/web`: each song card gets a "Split into parts" button → 4 stem players. +1 test. 6 web tests total.
- **Keys:** `REPLICATE_API_TOKEN` (+ `ANTHROPIC_API_KEY` for M3) in a gitignored root `.env`, loaded at startup via `python-dotenv` in `main.py`.
- **Cost:** ~2–6¢ per song, cached; validated live end-to-end.

## Known follow-ups

- CI `verify` job is Node-only today; add a Python (pytest) job when a GitHub remote is set up. Also point the coverage job at `apps/web/coverage/` (or emit to repo-root `coverage/`).
- Non-Western (Indian/Bollywood/Punjabi) key + structure detection is weaker — hand-verify those demo pairs.
- Before any public exposure (per the M1 security review): sandbox/resource-limit FFmpeg on untrusted input, add rate-limiting + body-size limits at the proxy, and add HTTP-level traversal/oversize tests.
