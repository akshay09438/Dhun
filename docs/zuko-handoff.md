# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-08 (**second planning session of the day — still NO code written**). The founder shared **5 real house/techno × Bollywood reference mashups** with detailed narration, which produced **the actual judgment recipe for this genre** AND **corrected the earlier build plan** (the "beat-swap / Song 2 as itself" hero move is wrong for house × Bollywood). Working-tree changes are docs-only (this handoff + an implementation-plan drift entry + a "superseded" banner on the plan doc). Code and test suite **untouched** (last known green: 181 backend + 39 web).

## Where things stand (one breath)

Both V1 features (offline mix + live steering) remain built and founder-confirmed on the curated "Father Ocean shelf." **The big outcome of today is the judgment recipe for house × Bollywood, distilled from the founder's own reference mashups** — this is the taste the app must encode. Key correction: **the house/electronic beat is the constant FOUNDATION; a DJ does NOT swap to the Bollywood beat** (so the earlier plan's "Song 2 plays as itself" move is dropped). **The real recipe:** align the Bollywood vocal's emotion to the house track's structure — **build-with-build, drop-with-peak (energy sync)**; put **vocal chops/hums on the drop** ("dum da ra dum", not full verses); the vocal rides **highs and lows**; Bollywood _music_ can **layer as accents** but the house beat stays the floor; **clean switches locked to the house build→drop**. Two concrete fixes fell out: **(A)** a **tempo "fast-track"** so slow songs get sped up instead of rejected — this unblocks the founder's #1 favourite pair, **Father Ocean × Tere Bina, which the app currently DECLINES**; and **(B) vocal chopping** (hooks/hums onto drops). Full detail: implementation-plan drift entry **2026-07-08 (2nd)**.

## In flight

- **NO half-done code. No code touched this session.** Only-tree changes are documents (this handoff, the drift entry, the plan-doc banner) — committed here.
- **The build plan `docs/richer-mashup-proof-plan.md` is PARTIALLY SUPERSEDED** (banner added at its top). Its "beat-swap / Song 2 as itself" centrepiece is **wrong for this genre — do NOT build it.** It will be rewritten in "Phase 0" into a _House × Bollywood Recipe_ + updated plan.
- **The recipe is captured (in the drift log + here) but not yet written as its own doc, and not yet founder-approved.** Writing it up is the first Phase-0 task.
- **One open decision:** may I **pull the audio from the 5 YouTube references** for private analysis (to get hard build/drop/vocal-entry numbers)? Fine for the 50-person validation; not for public use. Founder to okay.
- **Suite state:** NOT re-run (no executable change). Last known green stands: **181 backend + 39 web, typecheck clean.**

## Do first next session

1. **Phase 0 (no risky code):** (a) if the founder okays it, pull the 5 reference mashups' audio and run them (and the source songs) through the app's **existing analysis** to extract objective build/drop/vocal-entry timings; (b) **write the "House × Bollywood Recipe" doc + a rewritten build plan** (replacing beat-swap with energy-sync + vocal chops + the tempo fast-track); (c) **founder reads + approves.**
2. **Phase 1 (heavy path, gated) — build in this order, each with tests-first + safety review + founder's yes on protected files + founder listen:** tempo fast-track fix (`fence`, safe surface — unblocks Father Ocean × Tere Bina) → energy detection: builds/drops/peaks (`analysis.py`, safe) → energy-sync arrangement (`plan`/`fence`, safe) → **vocal chops/hums on drops** (`workers/render.py`, DANGEROUS) → build/filter craft (`render.py`, DANGEROUS).
3. **Phase 2:** founder listens (ideally on **Father Ocean × Tere Bina**) and re-shows the same 3–4 testers who said V0.1 is "too simple."

## Verification evidence (which checks ran, what they returned)

- **No code changed this session → no checks re-run.** Honest baseline (from the 2026-07-07 handoff, re-verified there): backend `pytest -q` in `services/api` → **181 passed**; web `npm test` → **39 passed**; `npm run typecheck` → **clean**. Markdown-only edits cannot affect these.
- **This session's artifacts are documents only:** this handoff, one implementation-plan drift entry, and a "superseded" banner on `docs/richer-mashup-proof-plan.md`.

## Open escalations

- **PLANNED dangerous-surface work (a claim about the FUTURE build, nothing verified yet):** the recipe build will edit `workers/render.py` (vocal chopping, energy-synced drops, build/filter craft) and likely `services/api/app/planner/validate.py` (rules for the new moves). These are the quality guardrails — they MUST go through test-author + adversarial quorum + confirm-and-apply + the founder's ears before merge. Nothing here is built or verified.
- **Tempo fast-track = a real behaviour change to re-check by ear:** stretching very slow songs (e.g. Tere Bina, ~half tempo) up to the house tempo _will_ risk warble on extreme pairs; the founder accepts this to unblock the pair, but it must be ear-tested, and we may need octave-folding / smarter stretch rather than a naive big stretch.
- **CLAIM to re-verify — the ±8%→±11% band widening** (`fence.SAFE_STRETCH_LO/HI` = 0.89/1.11): founder-accepted anti-warble relaxation for ALL mixes; the tempo fast-track work will touch this same area — re-confirm by ear.
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do **not** make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Catalog audio + `data/library/manifest.json` are LOCAL-ONLY** (gitignored `data/`). Any new machine / cloud deploy must re-source the songs (`song-dropbox/` on the Desktop) and re-ingest. Not reproducible from git alone.
- **Upload route** (`services/api/app/routes/songs.py`, dangerous) still exists (operator-only). Streaming size-cap + FFmpeg timeout in place; rate-limit + duration cap still open — re-verify hardening before any public deploy. (Note: the founder increasingly talks in terms of users "dropping" songs — if open uploads return, this handler's hardening becomes front-line.)
- **`main` is behind** (M4 tip); all work is on `feat/m5-live-control` (pushed). Merge deferred by the founder.
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live. (ngrok free = one tunnel at a time; claim the free static domain for a stable URL.)
**Flow:** pick a beat + a vocal from the dropdowns → Make my mix → Play (tap parts / Beat up / chips / type commands / drag the transport) → Export.
