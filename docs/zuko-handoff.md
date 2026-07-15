# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-15 (**BEST-PARTS is now LIVE on `main` and is the DEFAULT for every mix and set — the toggle was removed. Multi-set UI + the vocal chain were also merged to `main` this session. Three new BEATS were added to the catalog (LOCAL-ONLY). `main` @ `ab10f88`; 416 backend + 49 web + typecheck green; `render.py`/`validate.py` UNTOUCHED.**)

## Where things stand (one breath)

`main` (@ `ab10f88`) is the shipped MVP and it all merged this session:

- **Best-parts is the DEFAULT, no toggle.** Every finished mix (and each half of a set) is auto-cropped to its ~180s highlight — cut points snapped to vocal-silent phrase boundaries (no chopped lyric), a build-up at the start and wind-down at the end, chained on the beat for sets. A two-song set is now ~5–6 min instead of ~15. **Regenerate still works** (the full render is kept behind the scenes and is what a new take / the set-join build from; the user hears the highlight). Post-render only — the mixing engine is unchanged.
- **Multi-set UI + vocal chain**: previously on branches, now merged and live.
- **Catalog grew 2→5 beats**: added **Innerbloom** (122 BPM, copied free from the sandbox), **Rapture (Black Coffee)** (120 BPM/9A) and **Anchor Point (Ahmed Spins)** (122 BPM/8A) — split+analyzed on Replicate (founder-OK'd). All in the ~120–128 blend band. Catalog = **5 beats + 5 vocals**.
- The app is **running locally at `http://localhost:8000`** (fresh production build; backend serves the UI). Nothing public.

## In flight - done vs left

Nothing is half-done this session — everything landed and is green.

**DONE + MERGED this session:**

- Best-parts ported to the live app (first gated OFF behind a toggle → PR #3; then made the DEFAULT with the toggle removed → `main` @ `ab10f88`). New `workers/best_parts.py`; wiring in `routes/mix.py` (single-mix highlight, full render kept canonical, read-before-crop race fixed) and `routes/set.py` (always-crop, resilient).
- Multi-set UI (PR #2) and the vocal chain — merged to `main`.
- 3 catalog beats added (⚠️ LOCAL-ONLY — see escalations).

**LEFT (pre-launch, before the ~50-user test — not blocking, carried from prior handoffs):**

- The **`storage.py` cache-eviction sweep** — now also orphans `*.bestparts.wav` and `*.set.wav` (unbounded local disk). Dangerous surface.
- **Short-clip (15–30s) export + final loudness master** (M6 polish).
- The **R1 hand-off** pre-launch items (see the 44th drift-log entry) and re-checking each NEW pair's hand-off by ear.

## Do first next session

Ask the founder which: (a) **ear-check the new beats** (Innerbloom / Rapture / Anchor Point × the vocal catalog) and confirm the best-parts highlight fires cleanly on real pairs (not silently falling back to full); or (b) start the **pre-launch cleanup** — the `storage.py` cache-eviction sweep is the most durable owed item; or (c) **M6 polish** (short-clip export + loudness master), the last thing before the ~50-user validation test.

## Verification evidence (which checks ran, what they returned)

- **Backend:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **416 passed** (~96s). Includes the new `test_mix_serves_best_parts_highlight_keeping_full_render` (asserts the highlight derivative is built + served while the full render is kept).
- **Web:** `npm run typecheck` → clean (`tsc --noEmit`); `npm test` → **49 passed** (8 files).
- **Catalog live:** `GET http://localhost:8000/library` → 5 beats (Father Ocean, I Adore You, Innerbloom, Rapture, Anchor Point) + 5 vocals; the 2 Replicate-ingested beats have full stems + analysis cached (7 files each). New tempos measured: Rapture 120 BPM/9A, Anchor Point 122 BPM/8A.
- **Best-parts crop** verified on the FastAPI test fixtures (derivative built before 'ready'), and earlier this session founder-ear-approved on real pairs in the sandbox (Father Ocean × Der Lagi, I Adore You × Tujhe) and as an arc'd set.

## Open escalations / re-verify next session (claims, not settled facts)

- **`render.py` and `validate.py` were NOT edited this session** — best-parts is a post-render crop that imports `render.py` helpers READ-ONLY. This is a CLAIM: re-verify with `git log --oneline -1 -- workers/render.py services/api/app/planner/validate.py` (should predate 2026-07-15) before trusting it.
- **`_GOOD_PARTS_WINDOW_ENABLED` is still `False`** (the old crop-then-arrange window — distinct from best-parts, which is the opposite approach). Untouched; re-confirm it stays off.
- **⚠️ The 3 new catalog beats are LOCAL-ONLY.** `data/library/manifest.json` is GITIGNORED, so the additions + their cached stems/analysis live only on the founder's machine — they will NOT transfer to another clone/machine or a deploy. Re-verify the catalog on any new environment.
- **Best-parts falls back to the full mix on any crop failure** (mix route + set route both). This means a broken crop would silently ship full-length instead of the highlight — confirm by ear that the crop actually fires on each real pair, not just that the app "works".
- **`storage.py` cache-eviction sweep** (dangerous surface) is still owed and now orphans two more WAV kinds — do not treat disk as bounded.
- **CORS lockdown** (44th) is in place but must be re-verified before any public exposure (`Start-PromptDJ.bat` / ngrok).
- **Local dev server** `http://localhost:8000` is running from a background process this session; it will stop when the machine/session ends — relaunch with the two commands in the functional spec, or `Start-PromptDJ.bat` for a public link.
