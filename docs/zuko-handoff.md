# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-09 (**Production + diagnosis session. NO app code changed — `git status` clean, engine still `m5o.0`. Found and fixed the founder's "great this morning, bad now" regression: it was the AI arrangement path vs the deterministic RULES path, NOT a code change. Delivered 4 full-length "final test" mashups built on the rules engine. Suite green: 332 backend + 39 web, typecheck clean — re-run fresh at handoff.**) All prior feature work remains on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main**.

## Where things stand (one breath)

The founder asked for a continuous 4-mashup "final test" set (Father Ocean×Tere Bina, I Adore You×Tujhe Bhula Diya, Innerbloom×Dooriyan, Rapture×How Deep Is Your Love), then — after hearing them — reported the mixes were "very bad" now but "very great this morning." **`superpowers:systematic-debugging` found the real cause and it was NOT any of today's commits:** the mixes were rendering through the **AI/LLM arrangement path** (`_ai_arrange`, used whenever `ANTHROPIC_API_KEY` is set), while every loved render was made with the **deterministic RULES engine** (key popped). Proven by sample-correlation on I Adore You×Tujhe: rules-path == this morning's file (**corr 1.000**), AI-path == a different arrangement (**corr 0.919**). Fix = build on the rules path. **4 full-length, both-vocals mashups were delivered** to `Desktop/DJAI SONGS` (`FINAL TEST 1–4 …(full).wav`), freshly rendered on the rules engine. **The engine itself was never touched this session** — all work was in session-scratch scripts.

## In flight — done vs left

- **Nothing is half-built or red. `git status` is clean — no app code changed this session.** Everything this session was scratch scripts + the gitignored data cache + files saved to the Desktop.
- **The "final test" deliverables are done** (4 full mashups, rules path, in `Desktop/DJAI SONGS`). **Open acceptance: founder ear-test** — is the mashup quality right now that they're on the rules engine?
- **2 new catalog songs are now processed + cached** (free to reuse): Rapture, How Deep Is Your Love. See the id map below.
- **A set-assembly prototype exists in scratch but was NOT adopted** (`scratchpad/set_pro.py`: tempo-lock all mashups to one BPM + beat-align each seam + a volume/filter intro build). The founder pivoted to individual full mashups instead. The shipped `workers/set_render.py` is still just a plain 4 s crossfade (no beatmatch) — if a real continuous set is pursued, that tempo-lock/beat-align logic is the starting point.
- **Carried forward, UNCHANGED (from the prior handoff):** variation-in-app (first play fresh + keep/lock button); the set-builder API+screen; loudness master + short-clip export (M6).

## Do first next session

1. **⭐ Product decision the founder needs to make: should the app DEFAULT to the rules path?** Today's regression happened because the app uses the AI arrangement whenever the Anthropic key is present — and that is the arrangement the founder consistently dislikes. The loved mixes are all rules-path. Options: default to rules; or fix the AI path to arrange better; or make it a user toggle. **This is the highest-value open item — it's why the mixes felt "broken."**
2. **Founder ear-test the 4 `FINAL TEST …(full).wav` mashups** now that they're on the rules engine.
3. Then the carried-forward roadmap: variation-in-app → set-builder → mastering/clip-export → drive the running app end-to-end → the ~50-creator test.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **332 passed** (~46 s). Root → `npm run typecheck` → **clean (tsc --noEmit)**. Root → `npm test` → **39 passed (7 files)**. `git status --short` → **empty (no code changed this session)**; branch `feat/house-bollywood-energy-sync`.
- **Root-cause proof (sample-correlation, I Adore You × Tujhe Bhula Diya, full-length):** rules-path render vs this morning's `08 - Adore You x Tujhe Bhula Diya.wav` = **1.000** (identical); AI-path vs morning = **0.919** (different arrangement); AI run A vs AI run B = **1.000** (AI is deterministic, just arranges differently). Delivered `FINAL TEST 2` vs morning `08` = **1.000**; `FINAL TEST 1` vs morning `03` = **0.945**.
- **Freshly rendered, not pasted (proof):** `FINAL TEST 1–4` mtimes are 21:26–21:27 today (morning files are 02:52–03:20); `FINAL TEST 4` (Rapture × How Deep) has no morning counterpart at all — those songs were only processed today.

## Open escalations

- **⭐ PRODUCT DECISION (founder): default the app to the rules arrangement path** (see Do-first #1). The AI path is live whenever `ANTHROPIC_API_KEY` is set and produces the arrangement the founder dislikes.
- **⚠️ Pre-existing, carried forward, UNCHANGED (block merge to main):** (a) the R1 relaxation in `validate.py` (Song-1 tail ≤ `LEAD_XFADE_SECS` overlap) is still NOT cleanly adversarially cleared; (b) lock **CORS** in `config.py` to the real origin before deploy. Also re-verify (claims, not facts) the good-parts window's two dangerous-surface edits (`workers/render.py`, `services/api/app/planner/validate.py`) before merge.
- **Branch NOT merged to main; `gh` CLI NOT installed here.** Open the PR via GitHub web: https://github.com/akshay09438/Dhun/compare/main...feat/house-bollywood-energy-sync?expand=1
- **Cloud-upload note (not a live bug):** long tracks' 44.1 k WAVs are large (Rapture 82 MB) and the whole-file Replicate upload stalled. The scratch scripts work around it by uploading a compact 192 k MP3 of the same audio. If real users upload long songs, port that into `app/audio/stems.py` + `analysis.py`.

## Reference — song id map, cache, how to run

- **song_id = sha256 of the normalized WAV.** Cached catalog ids: Anchor Point=`2c17fc64`, Father Ocean=`ac59f8c4`, Innerbloom=`2471e18e`, Dooriyan=`c4b28366`, Maula Mere=`6608cb48`, Der Lagi=`bbab7b9f`, Don't Start Now=`c0c6ab91`, Tere Bina=`6ad69035`, Jee Karda=`2294a715`, Dil Ye Bekarar=`73431441`, Tujhe Bhula Diya=`fedc95c9`, I Adore You=`b8696c4d`, **Rapture=`7f0b66c9` (new this session)**, **How Deep Is Your Love=`4e246293` (new this session)**.
- **Data cache** at `services/api/data/` (gitignored) — all stems + analyses cached, re-renders FREE. Source MP3s in `song-dropbox/`.
- **Founder ear-test loop (no cloud cost — cache present):** **pop `ANTHROPIC_API_KEY`** (`os.environ.pop("ANTHROPIC_API_KEY", None)`) → this forces the **RULES path, which is the arrangement the founder likes** (the AI path arranges differently). Then `build_mix_plan(a1, a2, take=N)` → `render_mix(plan, {drums/bass/other/vocals}, song2_vocal, out)`. Analysis JSON in `data/` is missing the `status` field — inject `status="ready"` when loading via `TrackAnalysis.model_validate`.
- **Where mixes are saved:** `C:\Users\Akshay\OneDrive\Desktop\DJAI SONGS`. Save under a **fresh distinct filename** (same-name overwrites can serve from the OS/OneDrive cache). **Windows filename gotcha:** no `>` in filenames.
- **Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
