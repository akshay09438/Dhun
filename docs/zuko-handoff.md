# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-16 (**Two merged batches: (1) catalog expansion — +7 vocals and a D&B "bridge" beat (Merrygo) + two per-song planner overrides; (2) set transitions — a set is NEVER refused for tempo again; a seam whose tempos can't blend is CUT like a real DJ. Both MERGED + pushed; `main` @ `05e2a8e`. 427 backend + 49 web + typecheck + lint all green. `render.py`/`validate.py` UNTOUCHED. Catalog AUDIO is LOCAL-ONLY.**)

## Where things stand (one breath)

`main` @ `05e2a8e` is the shipped app and everything below is IN it. The app runs locally at `http://localhost:8000` (a background process — it dies with the session; relaunch command at the bottom). Nothing is public.

- **Catalog: 6 beats + 12 vocals (18 entries, LOCAL-ONLY).** +7 Bollywood/Punjabi vocals (Nadan Parinde, Uff Teri Ada, Jugni Ji, Wari Jawa, Tere Bin, Mera Yaar, Khuda Jaane), each split/analyzed with its hook marked. Reusable ingest tool: `scripts/ingest_catalog.py`.
- **A D&B "bridge" beat, "Merrygo"** (~85 BPM) so the slow vocals (80–103) have a partner — the house beats (120–122) are too far for the ±11% mix band.
- **Two per-song planner overrides, dormant for every other song:** `instrumental_beats.py` (Merrygo contributes music only) and `main_drops.py` (Merrygo's drop hand-marked at 0:40).
- **Per-seam set transitions (the big one).** A set now picks each transition from the tempos either side of it: **blend where they agree** (unchanged), **CUT where they can't**. Nothing is ever dropped for tempo.

**The catalog's two camps** (this explains almost every "why won't this work" question): the **fast camp** — I Adore You, Father Ocean, Innerbloom, Rapture, Anchor Point — all render at 120–127; the **slow camp** — Merrygo alone — renders at 85–92. Within a camp → blend. Across camps → cut. Merrygo is the only slow beat, so the cut is the rare escape hatch, not the norm.

## ⚠️ Lesson from this session (carry it forward)

The agent twice asserted, confidently and **without reading the code**, that joining an 85 BPM mix with a 120 BPM one would make vocals warble ("chipmunks"), then that the overlap was "~4 bars". **Both wrong.** `workers/set_render.py` contains **no time-stretch at all** — a set join never changes anyone's speed, so nothing there can warble; and the overlap is **8 bars = 22.6s**. `set_tempo_plan`'s master tempo was computed and **never applied**. The founder pushed back ("I want the rule to vanish") and was **right** — the ±11% band on the SET join was inherited from the MIX stage (where the stretch is real) and only ever guarded a messy seam.

**Lesson: read the engine before explaining what the engine does — especially when refusing the founder's request on the engine's behalf.** A second bug (below) was then caught only by measuring the rendered WAV instead of trusting the API's own reported duration.

## In flight - done vs left

**Nothing is half-done.** Everything this session built is merged, green, and pushed. Catalog audio is local-only by design (gitignored).

**DONE (merged to `main`):**

- Catalog +7 vocals + Merrygo (trimmed its 0:00–22.68s piano intro, re-ingested → id `4fc82b59…`); hooks marked for all 7 (2 to founder ear-marks).
- `instrumental_beats.py`, `main_drops.py`, `scripts/ingest_catalog.py` (new); `plan.py`, `fence.py`, `hooks.py`, `mix.py` (ENGINE_VERSION → m6.8).
- **Set fix 1:** the set tempo is reconciled on each MIX's real playing tempo (`fence.arrangement_options()["master_bpm"]`), not the raw song BPMs — the old way voted with each vocal's ORIGINAL tempo, which the mix has already stretched away, and dropped joinable sets (even two on the SAME beat).
- **Set fix 2:** `set_render.tempo_blendable()` + `CUT_RAMP_SECS`; `assemble_beatmatched_set` picks the transition PER SEAM. `routes/set.py` no longer declines for tempo. `SET_PLAN_VERSION` s2→s3 (invalidates sets only; mix renders stay cached).
- Docs: functional spec, technical spec, implementation-plan drift #49, #49b, #50, #51.

**LEFT (pre-launch, carried forward — not blocking):**

- The **`storage.py` cache-eviction sweep** — the most pressing owed item. The disk hit 0 bytes free TWICE this session (~2.5 GB of regenerable renders + stale pytest temp cleared, with founder consent). Dangerous surface. Until then, disk must be watched by hand.
- **Short-clip (15–30s) export + final loudness master** (M6 polish) — the last thing before the ~50-creator test.
- **Founder ear-check still owed** on: the new vocals over Merrygo (drop at 0:40, no lyric overlap) and the **live in-app cut** (they approved the standalone `B - clean cut.wav` render, NOT yet a set built through the app).
- **The Play screen still reports a drop badly** — a small grey "skipped" card AFTER rendering. Much less reachable now (only a fence-level mix decline drops anything), but the founder explicitly deferred the warn-up-front fix. Offer it again.

## Do first next session

Ask the founder which: (a) **ear-check** the live Merrygo cut + the new vocals; or (b) the **`storage.py` cache-eviction sweep** (most pressing owed item — the disk filled twice); or (c) **M6 polish** (short-clip export + loudness master); or (d) **a second slow beat (~80–95 BPM)** so the slow camp has variety, which they floated and did not decide.

## Verification evidence (which checks ran, what they returned)

All run on merged `main` @ `05e2a8e`, 2026-07-16:

- **Backend:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → **427 passed** (~99s).
- **Web typecheck:** `cd apps/web && npx tsc --noEmit` → **exit 0**.
- **Web tests:** `npx vitest run --pool=forks --poolOptions.forks.singleFork=true` → **8 files, 49 passed**.
- **Lint:** `npm run lint` → **exit 0**.
- **End-to-end on the LIVE API with real songs** (the set work — not just unit tests):
  - Merrygo(85) + I Adore You(120) → **kept 2/2**, CUT at **90.335s** (= member 1's exact length, zero overlap), manifest **282.325s** == real WAV **282.33s**.
  - Merrygo(85) + Merrygo(85) → kept 2/2, **BLEND** at 67.76s, manifest == WAV.
  - All **64** I-Adore-You × Father-Ocean vocal combinations → **64 blend, 0 cut** (they render at 120 vs 122 = 1.7% apart).
- **Red/green proof** on the tempo-model fix: `test_set_keeps_both_sets_on_one_beat_whatever_the_vocals_original_tempos` FAILS on the old code with the exact bug message ("too far from the set's tempo") and passes on the new. Verified by stashing only the fix.
- **Marked-drop (earlier batch):** hook anchors at 0:40 on Merrygo × {Jugni Ji, Mera Yaar, Khuda Jaane}; 0:37 on Tere Bin (tempo-shifted grid, same musical spot). 0s of Song-1 vocal on all four.

## Open escalations / re-verify next session (claims, not settled facts)

- **`_seam_positions` (`routes/set.py`) is a SECOND copy of `assemble_beatmatched_set`'s sample accounting.** It ALREADY drifted once this session — the cut shipped a correct 282.33s of audio while the manifest claimed 259.75s and put the seam at 67.76s instead of 90.34s (the Play screen draws transitions from `seam_at`). `test_seam_positions_match_the_rendered_set_across_a_cut` now pins it to the real WAV. **Any new branch in the seam engine needs its twin there.** This duplication is a standing hazard — consider collapsing the two into one accounting function.
- **`render.py` / `validate.py` were NOT edited this session.** CLAIM: re-verify with `git log --oneline -1 -- workers/render.py services/api/app/planner/validate.py` (should predate 2026-07-15) before trusting it. `workers/set_render.py` WAS edited — it is NOT on the dangerous list (only `workers/render.py` and `workers/**/storage*.py` are).
- **⚠️ ALL catalog additions are LOCAL-ONLY.** `data/library/manifest.json` + stems/analyses are gitignored, so the 8 new songs live ONLY on the founder's machine — they will NOT transfer to another clone or a deploy. The instrumental-only + main-drop markers key off content id `4fc82b59…`; on any re-ingest elsewhere the id must match or the markers silently won't apply.
- **Both batches were merged straight to `main` with NO pull request**, at the founder's explicit request (`gh` is not installed; they chose "skip the PR — merge it directly", then "give me everything updated in the project folder and GitHub"). Deviates from CLAUDE.md's "never commit to the protected branch directly". Mitigations run: work committed on a branch first, merged `--no-ff` (each batch is a distinct revertable merge commit), suite green before AND after. **Not a new default — offer the PR path again.** Durable fix: install `gh` (founder declined for now).
- **`test_mix_is_cached` fails with a JSONDecodeError if a live uvicorn server runs concurrently with the suite** (it reads the real data dir mid-write). Green with the server stopped — 427 passed. Spawned as a separate task; a test-isolation gap, not a product bug. **Stop the server before trusting a red suite.**
- **The default `npm test` OOMs on this machine** ("JavaScript heap out of memory") under load — a runner-memory flake, not a real failure. Single-fork passes 49/49. Making single-fork the default needs sign-off (`vitest.config.*` is a dangerous-surface glob).
- **`_GOOD_PARTS_WINDOW_ENABLED` is still `False`**; best-parts (post-render crop) is still the default. Neither touched. Re-confirm.
- **Pre-existing uncommitted WEB edits remain in the working tree** (App.tsx, SetupScreen.tsx/.module.css, api.ts, api.test.ts, liveSchedule.test.ts, study.ts, study.test.ts). They predate 2026-07-15, are NOT from these sessions, and were deliberately NOT committed. Suite is green with them (49/49) but their intent is unknown. **Decide next session: finish or discard.**
- **CORS lockdown** (44th) must be re-verified before any public exposure.
- **Local dev server:** relaunch with `services/api/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir services/api --port 8000`, or `Start-PromptDJ.bat` for a public link. It does not survive the session.
