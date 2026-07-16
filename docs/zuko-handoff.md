# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-15 (**Catalog expansion session: +7 vocals and a Drum & Bass "bridge" beat ("Merrygo") that lets the slow vocals blend where house beats can't. Two new opt-in planner overrides shipped — instrumental-only beats + hand-marked main drops. Code committed on a branch (PR open); catalog AUDIO is LOCAL-ONLY. `render.py`/`validate.py` UNTOUCHED. 420 backend + 49 web + web-typecheck green.**)

## Where things stand (one breath)

`main` (@ `ab10f88`) is still the shipped MVP. On top of it, this session added catalog songs and two narrow planner behaviours (all backend/Python; the screens, flow, and mixing engine are unchanged):

- **Catalog grew to 6 beats + 12 vocals (18 entries, LOCAL-ONLY).** +7 Bollywood/Punjabi vocals (Nadan Parinde, Uff Teri Ada, Jugni Ji, Wari Jawa, Tere Bin, Mera Yaar, Khuda Jaane), each split/analyzed with its hook marked. A reusable ingest tool was written: `scripts/ingest_catalog.py`.
- **A D&B "bridge" beat, "Merrygo"** (an adiwav D&B remix of Khuda Jaane, ~85 BPM) — added because the 4 slowest new vocals (80–103 BPM) can't blend with the house beats (120–122) inside the ±11% safe stretch band. All four blend cleanly over Merrygo (+6% to −11%).
- **Two per-song overrides, both dormant for every other song:** `instrumental_beats.py` (Merrygo contributes music only — fixes ~45s of its own Khuda Jaane vocal overlapping Song 2) and `main_drops.py` (Merrygo's drop hand-marked at 0:40, since its flat energy defeats auto-detection — the vocal's hook now lands on the drop).
- Merrygo's piano intro (0:00–22.68s) was trimmed off and the beat re-ingested (final id `4fc82b59…`).
- The app is running locally at `http://localhost:8000` (background process; stops when the machine/session ends). Nothing public.

## In flight - done vs left

Nothing is half-done. Everything this session landed, is green, and is committed (code) — the catalog audio is local-only by design (gitignored).

**DONE this session (committed on the session branch):**

- 7 vocals + the Merrygo D&B beat ingested; hooks marked for all 7 vocals (2 to founder ear-marks: Nadan Parinde 1:35–2:05, Jugni Ji 0:09–0:29).
- `instrumental_beats.py` + `main_drops.py` (new); `plan.py`, `fence.py`, `hooks.py`, `mix.py` (ENGINE_VERSION → m6.8) edited; 4 new tests; version-pin test updated.
- Docs updated (functional spec, technical spec, implementation plan drift #49).

**LEFT (pre-launch, before the ~50-user test — not blocking, carried forward):**

- The **`storage.py` cache-eviction sweep** — now MORE urgent: the disk hit 0 bytes free TWICE this session (render caches + ~1.4 GB of stale pytest temp renders). Dangerous surface; still owed. Until then, disk must be watched by hand.
- **Short-clip (15–30s) export + final loudness master** (M6 polish).
- **Ear-check the new pairs by the founder** — BPM/analysis are verified by numbers, but the actual SOUND of each new vocal over Merrygo (and over the house beats where tempo allows) needs a listen. Indian/Punjabi analysis is the weaker link.

## Do first next session

Ask the founder which: (a) **ear-check the new mixes** — especially Merrygo × each of the 4 slow vocals (confirm the drop lands right at 0:40 and no lyric overlap), and the 3 tempo-compatible new vocals over the house beats; or (b) the **`storage.py` cache-eviction sweep** (now the most pressing owed item — the disk filled twice); or (c) **M6 polish** (short-clip export + loudness master), the last thing before the ~50-creator validation test.

## Verification evidence (which checks ran, what they returned)

- **Backend:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → **420 passed** (~81s). Includes the 4 new tests: `test_instrumental_only_beat_places_no_song1_vocal`, `test_merrygo_beat_is_marked_instrumental_only`, `test_hand_marked_main_drop_anchors_the_hook`, `test_merrygo_beat_has_a_hand_marked_main_drop`.
- **Web typecheck:** `cd apps/web && npx tsc --noEmit` → **exit 0** (clean).
- **Web tests:** `npx vitest run --pool=forks --poolOptions.forks.singleFork=true` → **49 passed (8 files)**. NOTE: the default `npm test` (multi-worker) OOMs on this machine under load ("JavaScript heap out of memory") — it is a runner-memory flake, not a real failure; single-fork passes. Consider making the default single-fork (but `vitest.config` is a protected file — needs sign-off).
- **Marked-drop behaviour (real data):** built plans for Merrygo × {Jugni Ji, Mera Yaar, Khuda Jaane} → vocal hook anchors at **0:40**; × Tere Bin → **0:37** (its grid is tempo-shifted, same musical spot). Instrumental-only: **0 s** of Merrygo's own vocal placed on all four pairs.
- **Tempo fit (app's own `tempo_plan`):** Merrygo 85 BPM × Khuda Jaane 80 (+6%), Mera Yaar 94 (−10%), Jugni Ji 95 (−11%), Tere Bin 103 (−11%) — all inside the ±11% band. The 4 slow vocals remain DECLINED against the 120–122 house beats (by design).

## Open escalations / re-verify next session (claims, not settled facts)

- **`render.py` and `validate.py` were NOT edited this session** — the new behaviour is all in `plan.py`/`fence.py` + two new marker modules. CLAIM: re-verify with `git log --oneline -1 -- workers/render.py services/api/app/planner/validate.py` (should predate 2026-07-15) before trusting it.
- **⚠️ ALL catalog additions are LOCAL-ONLY.** `data/library/manifest.json` + the songs' stems/analysis are gitignored, so the 8 new songs + Merrygo's trim live ONLY on the founder's machine — they will NOT transfer to another clone/machine/deploy. The instrumental-only + main-drop markers are keyed by content id `4fc82b59…`; on any re-ingest elsewhere the id must match or those markers won't apply. Re-verify the catalog on any new environment.
- **`_GOOD_PARTS_WINDOW_ENABLED` is still `False`** and best-parts (post-render crop) is still the default — neither touched this session. Re-confirm.
- **Merrygo's fixes are ear-unverified end-to-end.** The overlap fix, the trim, and the 0:40 drop are verified by numbers/plan inspection; the founder had confirmed the trimmed beat-only file is correct, but a full rendered Merrygo × vocal mix should be heard to confirm the drop and no-overlap by ear.
- **`storage.py` cache-eviction sweep** (dangerous surface) is still owed and now the disk-pressure risk is proven (0 bytes free twice). Do not treat local disk as bounded.
- **Pre-existing uncommitted WEB edits are in the working tree** (App.tsx, SetupScreen.tsx/.module.css, api.ts, api.test.ts, liveSchedule.test.ts, study.ts, study.test.ts) — they were there at session START, are NOT from this session, and were NOT committed here. The web suite passes with them (49/49), but their intent is unknown. Decide next session whether to finish or discard them.
- **CORS lockdown** (44th) must be re-verified before any public exposure.
- **Local dev server** `http://localhost:8000` runs from a background process; it stops when the machine/session ends — relaunch with `services/api/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir services/api --port 8000`, or `Start-PromptDJ.bat` for a public link.
