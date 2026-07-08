# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-09 (**Step 4 vocal chops: independent safety review FINISHED → dangerous risks disproven, tests landed, then the founder ear-tested it, it sounded dead, and he PARKED it. Next up: Step 5, the AI taste layer**). All work is on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main**. Everything is committed + pushed to origin. Suite green: **300 backend + 39 web, typecheck clean** (re-run fresh at handoff).

## Where things stand (one breath)

Last session left the vocal-chops change (`render.py` 🔒) committed but with its independent safety review **unfinished**. This session **finished that review** — a fresh 3-lens adversarial quorum + an independent test-author — and the **scary risks came back DISPROVEN**: it can't clip, can't crash, can't break the length/R1 overlap math, and the no-chop path is byte-identical. **7 chop tests landed** in `test_render.py` (mutation-verified). But the review also surfaced **two audible-quality risks the automatic checker can't hear**: (A) the mix goes quieter if a song's tempo reads above ~136 BPM, and (B) a **dead chop** if the vocal's first 0.22s is a breath. The **founder ear-tested the render and hit exactly (B)** — the 3:56 drop went dead for 2–3 seconds. His call: **park the chop** (it's a flourish, not core) and move to **Step 5**. The chop was parked cleanly on a safe surface. The rest of the session was **product education** (no code): explaining how Step 5 works and how the AI "reads" a song it can't hear (the energy graph).

## In flight

- **Nothing is half-built.** The vocal-chops review is complete and its outcome is fully recorded; the chop is cleanly parked; the suite is green.
- **Step 5 (the AI taste layer) is NOT started** — it was explained and aligned on conceptually this session, not coded. See "Do first."
- **The vocal chop is PARKED, not deleted.** `plan._flag_chop_on_biggest_drop(...)` is commented out in `build_mix_plan` (safe surface — `plan.py`), so no plan ever flags a chop and no mix can go dead on a breath. The engine machinery (`render._chop_pattern`, `Placement.chop`) + the 7 `test_render.py` tests stay in the tree, dormant and passing. **Revival condition (recorded):** only re-enable once the chop grabs a _punchy syllable_ (skip breaths/near-silence, find the strong onset in the first bar) instead of the raw first 0.22s slice — otherwise the dead-chop returns.

## Do first next session

1. **Step 5 — the AI taste layer.** Today the AI already chooses _where the vocals go_ (`plan._ai_arrange` sends Claude the song's energy/drops/sections/vocal-slices chart and gets back placements); the **beat moves are still fixed rules** (`fence.stem_moves_for_drops` / `beat_up_moves` / `breakdown_moves`). Step 5 extends the AI's job to **choosing which moves to make and where, from the same legal set the fence computes** — validated by the referee (`validate.py` already checks every StemMove regardless of origin, so likely little/no dangerous-file touch), with the fixed rules as the fallback. **Recommended:** run a short `superpowers:brainstorming` with the founder first to lock (a) the taste rules and (b) the one open product decision below — _then_ build behind the fence→AI→referee→fallback safety net.
2. **The one product decision to settle with the founder** (surfaced, not yet answered): does the AI just make **smart default move choices**, or also let the **user's typed words reshape the moves** ("darker" → more breakdowns; "high energy" → more beat-ups)? This changes the scope of Step 5.
3. **Clear the open R1 safety item before ANY merge to main** (see Open escalations) — still owed, untouched this session.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at this handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **300 passed in ~31s** (was 293 last session; +7 chop tests). Root → `npm test` → **7 files, 39 passed**. Root → `npm run typecheck` → **clean (tsc --noEmit, no errors)**.
- **Vocal-chops review (COMPLETED this session):** independent test-author wrote 7 tests (length-exactly-`out_len`; render-with-chop == render-without same length; chop-absent byte-identical to chop=False @0.0 diff; rhythmic onsets in the chopped bar; no-clip; edge-case gracefulness) — **mutation-verified** (a deliberately broken `_chop_pattern` is caught). 3-lens adversarial quorum: **clipping disproven** (peak-normalize is unconditional and runs after the chop, before write); **length/R1 invariant proven** (`_chop_pattern` returns exactly `out_len`; R1 computes overlap from plan fields only, independent of `chop`); **no reachable crash** (empty/1-sample/mono voc, bpm≤0, out_len≤0 all executed; the two isolated crashes are unreachable via the only call site). **Two quality findings** (A: >136 BPM loudness-gutting; B: dead chop on a breath) are the only non-`safe` residuals — both audible-only, both surfaced to the founder.
- **Founder ear-test:** the Desktop render `Der Lagi x Father Ocean - vocal-chops.wav` (chop at 3:56) demonstrated finding (B) live — the drop went dead. This drove the PARK decision.
- **Commits this session (all pushed):** `7fa3ecd` land vocal-chops review (tests + findings) · `24efd72` park Step 4 vocal chops.

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE (carried forward, unchanged): the pre-existing R1 relaxation is still NOT cleanly adversarially cleared.** To allow the natural vocal hand-off, `validate.py` R1 was loosened to permit a bounded overlap (Song 1's tail may run ≤ `LEAD_XFADE_SECS`=1.2s past Song 2's entry) WITHOUT an engine-guaranteed fade. A fresh adversarial pass on the bounded-no-fade relaxation MUST run before `feat/house-bollywood-energy-sync` merges to main. Not touched this session.
- **Vocal chop parked, not gone (a note, not a danger).** Reviving it is a one-line re-enable in `plan.py`, but the revival condition above (grab a punchy syllable, not the raw first slice) MUST be met first or the dead-chop returns. The engine change itself is already reviewed + test-covered.
- **Branch not merged; `main` is behind.** Merge deferred by the founder. Merging needs: the R1 re-verify above, and lock CORS in `config.py` to the real origin if deploying.
- **⚠️ The cached song data (`data/`) is CLEARED off the machine.** `data/` no longer exists (was gitignored; not reproducible from git). The source MP3s ARE present in `song-dropbox/` (Father Ocean, Der Lagi, Tere Bina, Tujhe Bhula Diya, Don't Start Now, Suniyan). **To render the real pair again (e.g. to ear-test a Step-5 mix or a revived chop), the two songs must be re-ingested (split + analyze via Replicate — a small cloud cost on the founder's credits); split-BEFORE-analyze** (the trap that causes empty vocal_regions → short mid-word vocals). No Claude cost for the deterministic render path.
- **The private ngrok link is DOWN** (session-bound). To restore: founder double-clicks **`Start-PromptDJ.bat`** (repo root), keeps the window open. Do not make it public (copyrighted audio + spends the founder's Anthropic/Replicate credits).
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch/heavy-audio locally — split/analyze go via Replicate; local DSP is FFmpeg + numpy/scipy. Work lean/sequential (memory-constrained).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Shareable link (self-hosted tunnel):** double-click **`Start-PromptDJ.bat`** (repo root) — builds the web app, starts the engine on :8000 (also serves the built UI), opens the ngrok tunnel; the public URL prints on the "Forwarding" line. Keep the window open + PC on = link live.
**Founder ear-test loop (no cloud cost ONCE songs are ingested):** render a WAV of the real pair via the deterministic pipeline (`os.environ.pop("ANTHROPIC_API_KEY")` forces the free rules path; `build_mix_plan` → `render_mix`) and open it from the Desktop under a **fresh, distinct filename** (same-name overwrites get served from the OS/OneDrive cache). Bump `ENGINE_VERSION` in `routes/mix.py` on each engine/plan change (now at **`m5n.0`**). NOTE: needs `data/` re-ingested first (see Open escalations).
