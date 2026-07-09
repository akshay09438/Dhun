# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-10 (**Hook-on-drop BUILT + founder-confirmed; phrasing tried & reverted; master mix-recipe written. Next: make the mixes "less plain" — root cause diagnosed, not yet built**). All work on branch **`feat/house-bollywood-energy-sync`**, **NOT merged to main**. Everything committed + pushed. Suite green: **302 backend + 39 web, typecheck clean** (re-run fresh at handoff).

## Where things stand (one breath)

This was a long, iterative "DJ-judgment" session, all validated by the founder's ear on the real Anchor Point / Bollywood pairs (their benchmark: these pairs have great real YouTube remixes). Landed: **hook-on-drop** — the drop now plays each song's **signature line** (not the loudest blob), marked per-song in `app/planner/hooks.py`, founder-confirmed. Along the way, two things were tried and rejected: **phrasing** (snap every change to a fixed 8/4-bar grid) was BUILT then **REVERTED** — it pulled vocals 1–3 bars off the real drop; and **strip-the-beat's-vocal** was **rejected** — the founder confirmed the natural fade-underneath hand-off is correct, not clutter. Also wrote the **master mix-recipe** ([docs/mix-recipe.md](mix-recipe.md)) — one plain-English rulebook for how a mix is made. The founder's **#1 open quality gap: the mixes feel "too plain"** — and we measured exactly why (see "Do first").

## In flight

- **Nothing is half-built.** Everything is committed, pushed, and green. No dangerous surface is mid-edit.
- **The "too plain" fix is DIAGNOSED but NOT started** — this is the agreed next build (see below).
- Engine version bumped **m5n.0 → m5o.0** for hook-on-drop (the reverted phrasing briefly used m5o.0 but never shipped).

## Do first next session

**Build the "less plain" fix: scale the number of vocal entries to the song's length.** Root cause (measured this session): the app always places a **fixed 3 vocal entries** (`plan._MAX_PLACEMENTS = 3`) regardless of song length. On a SHORT song (Adore You, 3.5 min) 3 entries fill it (gaps ~1 min → founder loved it); on LONG songs the same 3 entries leave huge empty stretches — **Anchor Point (5.8 min) → 1.9-min gaps; Innerbloom (9.2 min) → 3.0-min gaps of just beat, no vocal** → the "plain" feeling. **Fix:** place a vocal moment roughly **every ~60–75s** (more entries for longer songs) so the vocal keeps weaving back in like Adore You; hook still on the drops, other parts in between. Safe surface (`plan.py`/`fence.py`; the referee already guards one-voice-at-a-time). Founder agreed this is the next build.

**Then / bigger:** the fuzzier half of "too plain" — **vocal "play"/production** (roughen/energize the vocal to match the beat, e.g. Maula Mere's soft voice). This **brushes the non-goals** (autotune / style-transfer are out; light DSP energy/EQ may be in) — **scope it with the founder before building.**

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at this handoff:** `services/api` → `.venv/Scripts/python -m pytest -q` → **302 passed in ~23s**. Root → `npm run typecheck` → **clean (tsc --noEmit)**. Root → `npm test` → **web green (39; unchanged — no web files touched this session)**. `git status` → **clean**; HEAD after doc commit.
- **Hook-on-drop verified on the REAL pairs (local/cached, no cloud cost):** the drop placement's `vocal_src` starts exactly on the marked hook — 05 Dil Ye Bekarar → 42.0s ("Dil ye bekaraar kyun hai"), 10 Maula Mere → 28.9s ("Aankhein teri kitni haseen"); `validate_plan`/`validate_render` CLEAN. Founder ear-confirmed all marked hooks. New "(new Anchor Point x …)" renders are in `Desktop/DJAI SONGS`.
- **"Too plain" root cause measured:** entry counts + gaps — Adore You 3.5min/3-entries/max-gap 1.3min; Anchor Point 5.8min/3/1.9min; Innerbloom 9.2min/3/3.0min; Father Ocean 7.9min/3/2.9min.
- **Phrasing revert confirmed:** `snap_to_phrase` gone; 300→302 suite green after revert + hook-on-drop.

## Open escalations

- **⚠️ RE-VERIFY BEFORE MERGE (carried forward, unchanged): the pre-existing R1 relaxation is still NOT cleanly adversarially cleared.** `validate.py` R1 allows a bounded hand-off overlap (Song 1's tail ≤ `LEAD_XFADE_SECS`=1.2s past Song 2's entry) without an engine-guaranteed fade. A fresh adversarial pass MUST run before this branch merges to main. Untouched this session.
- **Vocal chop still PARKED** (`plan._flag_chop_on_biggest_drop` commented out); machinery + tests dormant. Revive only if it grabs a punchy syllable, not the raw first slice.
- **Hooks are keyed by song_id (content hash)** in `app/planner/hooks.py`. If a song is re-normalized/re-ingested and its hash changes, its hook mark won't match — re-key it. To add a song's hook: read its section map, mark the chorus slice, confirm by ear. Current marks: Dil Ye Bekarar 42.0, Jee Karda 55.0, Maula Mere 28.9 (all founder-confirmed).
- **Anchor Point × Jee Karda pairing dropped** (founder: doesn't work). Jee Karda's hook kept for other pairings.
- **Branch not merged; `main` behind.** Merge needs the R1 re-verify + lock CORS in `config.py` to the real origin if deploying.
- **Data cache present** at `services/api/data/` (gitignored) — all catalog songs' stems+analyses cached, so re-renders are FREE. Source MP3s in `song-dropbox/`. (Earlier this session I mistakenly checked the wrong path; the cache is at `services/api/data/`, not root `data/`.)
- **Environment truths (unchanged):** Windows-ARM can't run PyTorch locally — split/analyze via Replicate; local DSP is FFmpeg + numpy/scipy.

## How to run the app

**Local dev:** backend `.venv/Scripts/python -m uvicorn app.main:app --port 8000` (from `services/api`), web `npm run dev` (from root), open http://localhost:5173.
**Founder ear-test loop (no cloud cost — cache is present):** render the real pair via the deterministic pipeline (`os.environ.pop("ANTHROPIC_API_KEY")` forces the free rules path; `build_mix_plan` → `render_mix`), open from the Desktop under a **fresh distinct filename** (same-name overwrites get served from the OS/OneDrive cache — always name new renders distinctly, e.g. "new … .wav", per the founder's request). The scratchpad has reusable render scripts (`render_hooks.py`, `goodnight_batch.py`). Engine now at **`m5o.0`**.
**Where mixes are saved:** `C:\Users\Akshay\OneDrive\Desktop\DJAI SONGS`.
