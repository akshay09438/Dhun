# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-07 (long product/UX session — one-click flow → **full Electric Violet UI redesign** → **curated-catalog pivot** → the **"Father Ocean shelf"**; plus AI mix names, live-vocal fix, seekable transport, Beat up, Next-song. **215 tests green.**)

## Where things stand (one breath)

Both V1 features (offline DJ mix + live steering) were already done and founder-confirmed. This session was mostly **product + UX**, ending in a **curated-catalog MVP**. In order: (1) the **one-click "Studying your songs"** screen (auto split+analyze+mix, no manual buttons); (2) a **"Failed to fetch" fix** (dev CORS was hardcoded to :5173 — now trusts any localhost port); (3) the **"Beat up"** live move (melody+vocals duck so the beat drives) — the last V1 live command; (4) the **"Electric Violet" UI redesign** — the single page became **four screens** (Setup → Generating → Play → Export) in the founder's approved design (grey + one violet, Instrument Serif + Space Mono, 1280×800 console/stage frame), plus **AI-generated mix names**; (5) a **live-vocal fix** — the Play screen now plays the *arranged, beat-locked* vocal (same as the Download) instead of a rough continuous one that drifted, and the **transport is click/drag-seekable** with proper pause/resume; (6) a **"＋ Next song"** button; (7) the big pivot: **users no longer upload — they pick from a curated dropdown catalog** (`GET /library`, manifest-driven), because ear-tests proved tempo-matching ≠ good mashup (key/vibe is what blends, and the app can't pitch-shift). Dropdowns are **role-filtered** (beats vs vocals) and the **prompt box was removed**. The catalog is now a **single-beat "Father Ocean shelf"**: **Father Ocean** (122 / 10B) + four key-matched vocals (**Don't Start Now** clean; **Der Lagi Lekin** 10B/+9.9%; **Tujhe Bhula Diya** 10B/−8.3%; **With You** 11A/tempo-clean). To fit the two borderline Bollywood vocals, the clean-blend band was **widened ±8%→±11%** (`fence.SAFE_STRETCH`). All on branch `feat/m5-live-control`, pushed to GitHub. **176 backend + 39 web green.**

## In flight

- **No half-done code.** Working tree clean; `feat/m5-live-control` fully pushed to origin (in sync). Suite green (evidence below).
- **OPEN ACCEPTANCE — founder ear-test of the shelf** (the real "is it done"): mix **Father Ocean × each vocal** and judge by ear — (1) Der Lagi Lekin: warbly from the ~10% stretch? (2) Tujhe Bhula Diya: same, milder. (3) With You: the **key** (read 11A) — does it clash? (4) Don't Start Now: the known-good anchor. If any of 1–3 sound off → drop that vocal and **tighten `fence.SAFE_STRETCH` back toward ±8%**.
- **Servers left running** on the current code: backend :8000, web :5173 → http://localhost:5173. Catalog live (5 songs; all split + analyzed; Der Lagi render-checked end-to-end — passed B3+R3+R7+R6).
- **Two decisions the founder DEFERRED** (dismissed the questions, no action taken): (a) **merge `feat/m5-live-control` → `main`** (main is still at the M4 tip `0d0afea`; everything is in GitHub, just on the branch); (b) **deploy for a shareable web URL** (options laid out: quick tunnel vs private deploy).

## Do first next session

1. **Get the founder's ear verdict on the shelf** (above). This is the acceptance gate. Drop any warbly/clashy vocal; if the ±11% band makes *other* mixes warble, tighten it back.
2. **If the founder wants the web URL:** it's real work, not one-click. Needs: make the frontend API base configurable (currently hardcoded `http://localhost:8000` in `apps/web/src/lib/api.ts`), host the FastAPI backend (FFmpeg + keys), give the catalog audio + generated mixes a persistent home (object storage / disk), lock CORS to the real domain. **Copyright gate:** the 5 catalog songs are copyrighted — fine for a **private/unlisted** ~50-person test, **not** a public product; keep it private.
3. **Merge to `main`** if the founder says yes (fast-forward; all tests green).
4. **Then the road to validation:** M6 (loudness master + 14s clip export) if pursued; the ~50-creator test. (Cache-eviction, FFmpeg sandboxing still open but lower-priority now that users can't upload.)

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-07:

- Backend: `./.venv/Scripts/python -m pytest -q` in `services/api` → **176 passed** (in ~15s).
- Web: `npm test` (vitest) → **39 passed** (7 files); `npm run typecheck` → **clean**; `npm run lint` → **clean**.
- **Shelf render-check (no cloud):** built a real Father Ocean + Der Lagi Lekin plan+render — `stretch=1.099 (9.9%)`, 3 placements, 476s WAV, peak 0.891 — **passed B3 (stretch band) + R3 (on-beat) + R7 (per-bar beat-lock) + R6 (no clip)**. So the ±11% band genuinely renders the borderline vocal cleanly (mechanically; the *sound* is the founder's ear-test).
- **Catalog tempos verified on real audio** (not databases): Father Ocean 122/10B, Don't Start Now 125/10B, Der Lagi 111/10B, Tujhe Bhula Diya 133/10B, With You 118/11A, Suniyan Suniyan 130/4B (dropped — key clash).

## Open escalations

- **CLAIM to re-verify — the ±8%→±11% band widening** (`app/planner/fence.py` `SAFE_STRETCH_LO/HI` = 0.89/1.11): this relaxes the **anti-warble quality guard for ALL mixes**, not just the two Bollywood vocals. Founder-accepted to fit Der Lagi/Tujhe. `fence.py` is NOT on the dangerous-path list (so no guard fired), but it IS a quality-guardrail relaxation — **if the founder hears warble on any mix, tighten it back.** `validate.py`/`render.py` untouched (they read the constant symbolically).
- **Copyright (must decide before any public exposure):** the catalog holds 5 copyrighted commercial songs. Private/unlisted validation = defensible; a public URL streaming them = real legal risk. Re-decide at deploy time.
- **Catalog audio + `data/library/manifest.json` are LOCAL-ONLY** (gitignored `data/`). NOT in GitHub. On any new machine or deploy, the song files must be re-sourced (they're in `song-dropbox/` on this Desktop) and re-ingested. The catalog is not reproducible from git alone.
- **Upload route still exists** (`services/api/app/routes/songs.py` — a dangerous surface) but **users never hit it** (catalog-only); it's now operator-ingestion only. Attack surface is much smaller, but **re-verify its hardening before any public deploy** (streaming size cap + FFmpeg timeout are in place; rate-limit + duration cap still open).
- **`main` is behind** at `0d0afea` (M4). All session work is on `feat/m5-live-control` (pushed). Merge deferred by the founder.
- **Keys / cost:** `REPLICATE_API_TOKEN` + `ANTHROPIC_API_KEY` in the gitignored root `.env`. Catalog songs are pre-split/analyzed (cached) → a new catalog mix costs only the Anthropic arrangement/name/suggestion calls + local render (no Replicate). Regenerate = another AI mix.
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Memory-constrained — work lean/sequential (this session used inline scripts + background jobs, not heavy parallelism).

## How to run the app

See README.md. Quick: backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173. Both currently running. Flow: **pick a beat + a vocal from the dropdowns → Make my mix → Play** (tap parts / Beat up / chips / type commands / drag the transport). Add a catalog song: drop the file in `song-dropbox/`, ingest via the operator scripts (normalize+store → split → analyze → verify tempo/key → add a `data/library/manifest.json` entry).
