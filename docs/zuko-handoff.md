# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-07 (bug-fix + hardening + **first shareable link** session: fixed 3 real bugs on the Father Ocean × With You pair, ran a 4-reviewer mixing-pipeline hygiene sweep, made the whole UI **responsive for phone/tablet**, and stood up a **private ngrok link** so real testers can try it. **181 backend + 39 web green, typecheck clean.**)

## Where things stand (one breath)

Both V1 features (offline DJ mix + live steering) remain done + founder-confirmed; the app is the curated "Father Ocean shelf" (1 beat + 4 vocals, pick-don't-upload). This session was **fix + polish + first deploy**, in order: (1) **fixed the "Couldn't build this mix" crash** on Father Ocean × With You — the per-bar beat-lock buffer overflowed when a warp ended in a tiny trailing bar (`workers/render.py`, clamp each bar to its window); (2) **fixed Regenerate** — 3 of 4 catalog vocals detect ZERO vocal-regions, so every take reused the same ~16s clip; now falls back to the song's sung sections and rotates the slice + sub-window by `take` (also lets vocals play longer); (3) **fixed the Play button going dead after Regenerate** — the live-vocal file was served mid-write (a growing file → `Content-Length` overflow → the browser couldn't decode it); now rendered to a temp file and **atomically published**; (4) a **4-reviewer hygiene sweep** of the mixing pipeline — verdict _engine is sound, nothing ships a bad mix_ — plus two behavior fixes (shaky-song arc keeps first+last not first-two; regenerate window variety) and cleanups (dead code removed, `_hold`/slice helpers de-duplicated, several stale docs corrected: ±8%→±11%, R4/R5 "enforced"→"shaped upstream", beat-breath "silences"→"ducks", vocal-bus cache name, "uploads only"→catalog); (5) **responsive UI** — below 900px the fixed 1280×800 scaled canvas becomes a fluid, stacked, scrollable phone/tablet layout with ≥44px touch targets, 16px inputs, and a Play-screen reorder (transport leads, chat log trails); desktop unchanged; (6) **deployment prep + a live private link** — the built web app is now served BY the backend (single origin, no CORS), and an **ngrok tunnel** exposes it; a **`Start-PromptDJ.bat`** one-click launcher runs the engine + tunnel independently of Claude Code. All on branch `feat/m5-live-control`, pushed to GitHub (in sync).

## In flight

- **No half-done code.** Working tree clean; `feat/m5-live-control` fully pushed to origin. Suite green (evidence below).
- **THE LIVE LINK IS SESSION-BOUND — it dies when this Claude Code session closes.** The tunnel + servers I started this session (ngrok, the :8000 backend) are children of this session. The URL shown this session (`https://brinda-unprejudiced-nonbusily.ngrok-free.dev`) will STOP working once the session ends. **To bring a link back up independently: founder double-clicks `Start-PromptDJ.bat`** (repo root). Caveat: ngrok free allows **one tunnel at a time**, so nothing else ngrok can be running; and on free the URL is **a new random address each start** unless the free permanent domain is claimed (see "Do first").
- **Servers running RIGHT NOW (will stop at session end):** backend on :8000 (serves both the API and the built web app), Vite dev on :5173, ngrok tunnel. Do not assume these are up next session.
- **Deploy decision made (founder):** **private reach** (link shared only with the ~50 test group — matches the copyright constraint) + **tunnel now, cloud host later**. The tunnel is live; the permanent cloud host is the not-yet-started "later" step.
- **OPEN ACCEPTANCE — founder ear-test of the shelf (carried, still open):** mix Father Ocean × each vocal and judge by ear — Der Lagi Lekin / Tujhe Bhula Diya (warble from the ~9–10% stretch?), With You (key read 11A — does it clash?), Don't Start Now (the known-good anchor). If any sound off → drop that vocal and tighten `fence.SAFE_STRETCH` back toward ±8%.
- **Merge to `main` still deferred** — `main` is behind at the M4 tip; all session work is on the branch (pushed).

## Do first next session

1. **Founder ear-test of the shelf** (above) — still the real acceptance gate for the catalog.
2. **Make the private link permanent + effortless (if the founder wants ngrok as the ongoing setup):** claim the **one free ngrok static domain** (founder logs into their ngrok account, one button at dashboard.ngrok.com/domains) → then flip the commented `--url=YOUR-NAME.ngrok-free.app` line in `Start-PromptDJ.bat` so the link is the SAME every restart. Result: turn PC on → double-click → same link.
3. **When the founder validates people love it → the permanent CLOUD host** (the chosen "later"): package the backend (Docker + FFmpeg + Python), host on a small always-on VM / managed platform, set `ANTHROPIC_API_KEY` + `REPLICATE_API_TOKEN` as secrets, give the catalog audio + generated mixes a persistent disk, and **lock CORS in `services/api/app/config.py` to the real domain** (that CORS edit is the one dangerous-surface touch → gate it via confirm-and-apply). This removes the "PC must stay on" + random-URL + interstitial limits.
4. **Merge to `main`** if the founder says yes (all tests green).

## Verification evidence (which checks ran, what they returned)

Ran at handoff time, 2026-07-07:

- Backend: `./.venv/Scripts/python -m pytest -q` in `services/api` → **181 passed** (~17s).
- Web: `npm test` (vitest) → **39 passed** (7 files); `npm run typecheck` (`tsc --noEmit`) → **clean, no errors**.
- **Crash fix verified live:** the exact `mix_id` that crashed earlier in-session (`6232f4e9…`) now returns `status: "ready"` for all 7 real AI regenerate takes on Father Ocean × With You; reproduced-then-closed with `test_vocal_take_warped_survives_ffmpeg_length_overshoot`.
- **Play-button (atomic-publish) fix verified live:** a fresh Regenerate take through the running server served `409→202→200` with a complete 72 MB WAV and **no** `Content-Length` error (was a hard `LocalProtocolError` before); `test_vocal_bus_is_published_atomically`.
- **Regenerate variety verified live:** on the real pair, vocal-slice candidates went 1→4 and consecutive takes pull different vocal content.
- **Responsive verified** via computed-style inspection (screenshots were flaky on the live-audio Play screen): at 375px & 768px — zero horizontal overflow, stacked full-width, stage-first on Play, touch targets ≥44px, input 16px; at 1440px the framed 1280×800 scaled desktop design is intact (row layout, `overflow:hidden`, scale 1).
- **Deployment verified:** the single-origin backend serves `/` (app), `/library` (API), `/assets/*` (code) all 200; and the full app works end-to-end through the ngrok tunnel (page + JS/CSS + a 19 MB stem stream all 200).

## Open escalations

- **CLAIM to re-verify — the dangerous-surface render edits this session** (`workers/render.py`): (a) the per-bar clamp that fixed the crash, (b) `_hold` hoisted to module scope, (c) a docstring correction. Done via **confirm-and-apply** (founder approval recorded + cleared each time). **Verified this session** (181 tests + a real end-to-end render that passed the referee R6/R7 + the live smoke on the crashing pair). Re-verify only if the engine is touched again. `validate.py` was NOT touched.
- **CLAIM to re-verify — the ±8%→±11% band widening** (`fence.SAFE_STRETCH_LO/HI` = 0.89/1.11, carried from last session): relaxes the anti-warble guard for ALL mixes; founder-accepted to fit the two Bollywood vocals. If any mix sounds warbly, tighten back toward ±8%.
- **The live link exposes copyrighted audio + spends the founder's keys.** Reach was set to **private** (share only with the test group) — correct for the copyright constraint (5 commercial songs; private validation defensible, a public URL is not). Every mix spends Anthropic + Replicate credit; private reach keeps that capped. **Do not make the link public** without resolving licensing + spend limits.
- **Catalog audio + `data/library/manifest.json` are LOCAL-ONLY** (gitignored `data/`, not in GitHub). Any new machine or cloud deploy must re-source the song files (in `song-dropbox/` on this Desktop) and re-ingest. The catalog is not reproducible from git alone — this is the main thing a cloud deploy must carry over.
- **Upload route still exists** (`services/api/app/routes/songs.py`, a dangerous surface) but users never hit it (catalog-only). Streaming size-cap + FFmpeg timeout are in place; rate-limit + duration cap still open — **re-verify its hardening before any public deploy.**
- **`main` is behind** (M4 tip); all session work is on `feat/m5-live-control` (pushed). Merge deferred by the founder.
- **Environment truths (unchanged):** Windows machine can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — it builds the web app, starts the engine on :8000 (which now also serves the built UI), and opens the ngrok tunnel; the public `https://…ngrok-free.app` prints on the "Forwarding" line. Keep that window open + PC on = link live. (ngrok free = one tunnel at a time; claim the free static domain for a stable URL.)
**Flow:** pick a beat + a vocal from the dropdowns → Make my mix → Play (tap parts / Beat up / chips / type commands / drag the transport) → Export. Add a catalog song: drop the file in `song-dropbox/`, ingest via the operator scripts (normalize+store → split → analyze → verify tempo/key → add a `data/library/manifest.json` entry).
