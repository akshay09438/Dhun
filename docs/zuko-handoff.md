# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-09 (**TWO big features landed to near-complete: (1) GOOD-PARTS WINDOW — done + in the app, founder-ear-confirmed; (2) MULTI-SONG SETS — stitcher engine done + unlimited chaining proven, app-wiring pending. Plus a drop-detection fix + per-take VARIATION, both ear-confirmed.**) All work on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main** (~140 commits ahead). Everything committed + pushed. Suite green: **332 backend + 39 web, typecheck clean** (re-run fresh at handoff).

## Where things stand (one breath)

This session built the founder's two headline features. **Good-parts window** (the "part-songs" idea): every mix is now the beat's best **~90 seconds** — a window anchored on the main drop, starting on a low-density **cue point**, building up to the drop with the **hook on the loudest drop**, then a **wind-down outro**. It's live in the app's normal mix flow (not just direct renders) and founder-ear-confirmed (v4). **Multi-song sets**: a new stitcher (`workers/set_render.py`) joins any number of mashups with wind-down→cue-in crossfade transitions — the engine is done, tested, and **unlimited chaining is proven** (a 3-mashup demo), but the app screen/API around it is NOT built yet. Along the way, two founder ear-notes were fixed: the **main-drop ranking** (Father Ocean's 3:56 drop was being buried by phrase-averaging — now ranked by the hit) and **variation** (each take lands on a different strong drop — "never the same mix").

## In flight — done vs left

- **Nothing is half-built or red.** Everything committed, pushed, green. No dangerous surface mid-edit.
- **Good-parts window: DONE + IN THE APP.** `plan.build_mix_plan` windows the mix; `render.render_mix` crops the bed to `plan.window` (with a fail-loud guard); `validate.validate_plan` re-derives the windowed grid so windowed plans validate. The two dangerous-surface edits (`workers/render.py`, `services/api/app/planner/validate.py`) were adversarially reviewed SAFE + founder-confirmed (`.zuko/approve.js`) + applied this session.
- **Multi-song sets: ENGINE DONE, APP-WIRING LEFT.** `workers/set_render.py::assemble_set(mix_wavs, out, xfade_secs=4.0)` — equal-power crossfade join, peak/clip-safe, any number of mixes (7 tests; 3-mashup demo rendered). **Left:** a `/set` API (render each pair → assemble), a **set-builder screen** (queue mixes in order, "Make my set", play, export). Design: [docs/superpowers/specs/2026-07-09-multi-song-sets-design.md](superpowers/specs/2026-07-09-multi-song-sets-design.md). **Unlimited chaining is supported** (the "~2-4" in the design was only a testing suggestion — no code cap).
- **Variation: ENGINE DONE, APP-DEFAULT + LOCK LEFT.** `window.choose_window(a1, drops, take)` rotates the window across the genuinely-strong drops by `take`; vocal-slice variety already keyed off `take`. Regenerate already varies in the app. **Left:** make the **first** play fresh by default (app currently calls take=1), and a **"keep / lock this one"** button + persistence (founder decision: always-fresh + a lock for keepers).
- **Drop-intensity fix: DONE.** `window._drop_intensity` ranks a drop by post-onset energy (the hit), not the phrase average that buried dramatic drops. Father Ocean 3:56 went 0.37 → 0.885.

## Do first next session

The founder chose **"pause + handoff"** here. On resume, recommended order (founder-agreed direction):

1. **Variation in the app** (small): first play fresh by default + the "keep/lock this one" button. NOTE: variation changed the DEFAULT take — the founder-loved Anchor Point v4 window (3:55 drop) is now `take=2`, not `take=1` (take=1 is the 1:24 drop). Expected; the lock lets them freeze a favorite.
2. **The set-builder** (big): `/set` API + the screen (queue mixes, "Make my set", play, export). The stitcher already exists.
3. **Polish** (pre-existing M6): loudness mastering + short 15–30s clip export.
4. **Drive the RUNNING app end-to-end** to confirm in-app "Make my mix" produces the good windowed mixes with no surprises (verified via renders + tests this session, NOT yet by clicking through the live app).
5. The **~50 real-creator validation test**.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **332 passed** (~42s). Root → `npm run typecheck` → **clean (tsc --noEmit)**. Root → `npm test` → **39 passed (7 files)**. `git status` clean; all pushed to `origin/feat/house-bollywood-energy-sync`.
- **Founder ear-confirmed (real cached pairs, no cloud cost):** good-parts v4 (Anchor Point × Maula Mere — hook on main drop + wind-down ending); variation take 2 (Father Ocean × Der Lagi, 3:56 drop) — "the perfect one"; the 2-mashup and 3-mashup sets (transitions "pretty well"). Renders in `Desktop/DJAI SONGS`.
- **Drop fix verified on real data:** Father Ocean drops by hit — 6:17 (0.891), 3:56 (0.885), 1:02 (0.885), 7:20 (0.796); take 1→6:17, take 2→3:56, take 3→1:02.

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE — this session's two dangerous-surface edits.** `workers/render.py` (window bed-crop + fail-loud guard) and `services/api/app/planner/validate.py` (windowed-grid re-derivation) were adversarially reviewed **SAFE** and founder-confirmed this session — but per protocol those verdicts are CLAIMS; run a fresh adversarial pass before merging to main.
- **⚠️ Pre-existing, carried forward, UNCHANGED (block merge to main):** (a) the R1 relaxation in `validate.py` (Song-1 tail ≤ `LEAD_XFADE_SECS` overlap) is still NOT cleanly adversarially cleared; (b) lock **CORS** in `config.py` to the real origin before deploy.
- **Branch ~140 commits ahead of main; `gh` CLI NOT installed here.** Open the PR via GitHub web: https://github.com/akshay09438/Dhun/compare/main...feat/house-bollywood-energy-sync?expand=1
- **Key-compatibility is informational, NOT a blocker** (corrected this session — an earlier claim that it "auto-rejected" pairs was wrong; the app only declines on TEMPO). `camelot_fit` ±2 flags Anchor Point 8A × Maula Mere 5A as incompatible, but the pair builds and sounds fine. Optional future tweak; not a bug.
- **Data cache** at `services/api/data/` (gitignored) — all catalog stems + analyses cached, re-renders FREE. Source MP3s in `song-dropbox/`. **Name ↔ content-hash map** (song_id = sha256 of the normalized WAV): Anchor Point=`2c17fc64`, Father Ocean=`ac59f8c4`, Innerbloom=`2471e18e`, Dooriyan=`c4b28366`, Maula Mere=`6608cb48`, Der Lagi=`bbab7b9f`, Don't Start Now=`c0c6ab91`, Tere Bina=`6ad69035`, Jee Karda=`2294a715`, Dil Ye Bekarar=`73431441`.
- **Windows filename gotcha:** no `>` in filenames (the `->` in a set filename failed to write).

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Founder ear-test loop (no cloud cost — cache present):** `os.environ.pop("ANTHROPIC_API_KEY")` (forces the free rules path), `build_mix_plan(a1, a2, take=N)` → `render_mix(plan, {drums/bass/other/vocals}, song2_vocal, out)`. For a SET: render each pair's WAV, then `set_render.assemble_set([wav1, wav2, ...], out, xfade_secs=4.0)`. Save to `Desktop/DJAI SONGS` under a **fresh distinct filename** (same-name overwrites serve from the OS/OneDrive cache). Analysis JSON in `data/` is missing the `status` field — inject `status="ready"` when loading via `TrackAnalysis.model_validate`.
**Where mixes are saved:** `C:\Users\Akshay\OneDrive\Desktop\DJAI SONGS`.
