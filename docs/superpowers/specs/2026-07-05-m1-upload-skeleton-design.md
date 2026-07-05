# M1 — Upload Skeleton — Design

**Date:** 2026-07-05 · **Milestone:** M1 (the skeleton) · **Status:** approved, ready to plan

## Goal (one line)
A user opens the web page, drops two songs, clicks Process, and within a few seconds can play back both songs — each cleaned to a standard format and volume. Proves the whole pipe end to end.

## Why (the user job)
Serves Screen 1 ("bring your two songs") from the [functional spec](../../functional-spec.md). It is the foundation every later milestone stands on: consistent, standardized audio to work from. No DJ magic yet.

## Non-goals (explicitly NOT in M1)
Analysis (BPM/key/structure), stem separation, mixing/arrangement, the prompt box, live commands, a database, accounts, async job queue, and a built-in demo song pair. All deferred to their proper milestone.

## Approach
Simple & synchronous. The page uploads both files in one request; the backend cleans them with FFmpeg while the request waits (a few seconds); results are stored on local disk and returned to play. No queue, no DB — added in M2 when the genuinely slow steps (analysis, stems) arrive.

## Architecture
```
apps/web/            React + Vite + TypeScript — Screen 1 (upload + playback)
services/api/        Python + FastAPI — receives, cleans, stores, serves audio
  app/main.py        FastAPI app + CORS
  app/routes/songs.py  POST /songs (upload 2), GET /songs/{id}/audio  ← DANGEROUS (untrusted upload)
  app/audio/normalize.py  FFmpeg wrapper: decode → 44.1kHz stereo WAV → peak-normalize
  app/storage.py     save/read cleaned files by content hash  ← DANGEROUS (file writes)
  app/models.py      Pydantic: Song {id, original_name, status, url}
  app/config.py      settings (data dir, size/type limits)  ← DANGEROUS (config)
  tests/             pytest
data/                gitignored — cleaned WAVs on local disk
```
Root `package.json` wires the npm scripts CI expects (web typecheck/lint/test/coverage); Python tests run via `pytest` (a Python CI job is a documented follow-up).

## The flow
1. User drops **Song 1 (beat)** and **Song 2 (vocals)**, clicks **Process**.
2. Frontend `POST /songs` (multipart, both files).
3. Backend validates each: allowed audio type, under size cap. Reject otherwise (plain message).
4. `normalize.py` runs FFmpeg on each → 44.1kHz stereo WAV, peak-normalized.
5. `storage.py` saves each under a **content-hash filename** (never the user's filename) in `data/`.
6. Response: two `Song` records with `id` + `url`.
7. Frontend renders **two audio players**; user plays both back.

## The screen (Screen 1) — clean & product-looking
- Two labeled drop zones: "Song 1 — the beat", "Song 2 — the vocals" (drag-drop + click-to-pick).
- **Process** button (disabled until both chosen).
- States: **empty/first-run** (clear prompt), **selected** (filenames shown), **processing** (progress/spinner), **done** (two players), **error** (plain message + retry).
- Built with the project UI/UX skill (`anthropic-skills:ui-ux-pro-max`) for layout, hierarchy, and states.

## Error handling
- Non-audio / corrupt / oversized file → 400 with a plain reason; screen shows it, lets the user re-pick.
- FFmpeg failure on a file → clean error, nothing half-stored.
- Only one file chosen → Process stays disabled.

## Safety (the dangerous surface)
The upload handler (`routes/songs.py`) + `storage.py` are on the danger list. Controls:
- Allowlist audio MIME/extensions; reject everything else.
- Hard size cap (e.g. 30 MB/file) to prevent resource abuse.
- Never trust the uploaded filename — store under a computed content hash; original name kept only as a display label.
- Files written inside `data/`, never in a web-served code path; served back only via the explicit `GET /songs/{id}/audio` route by id.

## Testing (written with the code, TDD)
- `test_normalize.py`: a sample audio in → output is a valid 44.1kHz stereo WAV; corrupt/non-audio input raises a clean error.
- `test_songs_route.py`: valid two-file upload → 200 with two ids; oversized/non-audio → 400; `GET /songs/{id}/audio` returns the stored WAV; unknown id → 404.
- Web: the Uploader component renders each state (empty / selected / processing / done / error) correctly.

## Acceptance check (plain language)
> "I open the page, drop two songs, click Process, and within a few seconds I can play back both songs, cleaned to a standard format and volume."

## Follow-ups noted (not M1)
- Add a Python (pytest) job to CI when `services/api` lands.
- Content-hash storage sets up M2's per-file caching of analysis + stems.
