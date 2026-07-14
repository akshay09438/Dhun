# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-14 (**MULTI-SET UI BUILT + verified — Setup can stack up to 2 sets, a new `/set` builder joins them into one continuous beat-matched track, and the Play screen is stripped of live steering. On branch `feat/multiset-ui`, committed + pushed; a PR is one click from being opened (link below). NOT merged.** Suite: **415 backend + 49 web green**, typecheck clean. A **real 15:00 two-set was built and heard playing** in the running app. This reverses the "two-songs-only / no set screen" V1 non-goal AND retires live steering — both deliberate founder decisions this session.)

## Where things stand (one breath)

The MVP is on `main` (PR #1). This session added a **new feature on top, not yet merged**: **multi-set**. On the Setup screen you can now optionally stack a **second** song-pair (capped at two) and "Build the set"; a new backend `/set` route renders each pair through the _existing_ mix pipeline and joins them with the _shipped_ beat-matched seam engine into one continuous WAV (declining any off-tempo outlier with a plain reason); and the Play screen was **stripped** — Parts, chips, message log and the typed command bar are all gone (this **retires V1 Feature 2, live steering, from the UI**), replaced by a read-only **set line-up** and a simple one-file player that plays the finished mix (single) or set (two). The single-set path is unchanged and effortless. **The engine itself was not touched** — `render.py` / `validate.py` / `set_render.py` are import-and-call only. What is NOT done: the founder's **ear-listen** to the join, and merging the PR.

## In flight - done vs left

- **Nothing is half-built or red.** 415 backend + 49 web green; typecheck clean. All work committed on `feat/multiset-ui` (`319d507`) and pushed to `origin`.
- **DONE this session (branch `feat/multiset-ui`, off `origin/main` 5e446f3):**
  - **Piece 1 — Setup multi-set.** `SetupScreen` owns a 1–2-set line-up (`MAX_SETS=2`, `types.ts`), emits `onBuild(sets)`; console = the unchanged picker, stage = the running order (reorder ↑ / remove ✕). Single-set default unchanged. Note: "sets can only be added here, not during playback."
  - **Piece 2 — the `/set` route** (`services/api/app/routes/set.py`, NEW; registered in `main.py`). Async start-then-poll like `/mix`, cached by ordered pairs; thin orchestration over `set_render.set_tempo_plan` + `mix._run_mix` + `set_render.assemble_beatmatched_set`; returns a manifest (kept/dropped + reason + `seam_at`) + duration; `/set/{id}/audio` serves the joined WAV. Cap enforced (400 on >2). `tests/test_set_route.py` (6 tests, real render+join end-to-end).
  - **Piece 3 — stripped Play screen.** Removed the stem-bus `LivePlayer` + all steering from `PlayScreen`; new `lib/trackAudio.ts` (`TrackPlayer`, thin HTMLAudio wrapper) plays the finished track; left = read-only set line-up (now / next / dropped-with-reason), scrubber shows seam markers. `App` normalizes both paths; `study.studyAndBuildSet` reuses the studying checklist then `makeSet`; `api.ts` adds `startSet/getSetStatus/makeSet`; `ExportScreen` now takes `audioPath` (sets export too). Backend live routes left in place but unused (smallest change).
  - Docs updated to match (functional-spec, technical-spec as-built section, implementation-plan drift-log 47th).
- **DECISION (founder): live steering is retired from the app.** Made after being told twice exactly what the prompt bar / parts / chips did. The backend live endpoints are left in place but unused by the UI.
- **DECISION (founder): sets are added on Setup only** (no live mid-playback append — that needs gapless splicing, a separate future build) and **capped at 2** (keeps render time + file size down).
- **Left:** the founder **ear-listen** to a real two-set (does the join sound good?); **merge the PR**; the pre-launch `storage.py` cache-eviction sweep (now also orphans a new `*.set.wav` kind — see escalations); the ~50-creator validation test; a public/hosted deploy.

## Do first next session

1. **Open the PR (one click):** the branch is pushed; visit the pre-filled link →
   `https://github.com/akshay09438/Dhun/compare/main...feat/multiset-ui?expand=1` (title + body were pre-filled via the longer link generated this session). Or run `gh pr create` once the GitHub CLI is installed (it is **not** installed on this machine — `gh: none`).
2. **Founder ear-listen** to a real two-set before merge — the one thing CI can't judge. Fastest path: start both dev servers (`backend` + `web` via the preview tooling), open `localhost:5173`, pick a beat + vocal, "Add another set", pick another, "Build the set", press play, and listen to the transition (~7:22 into the Father Ocean example). Known-good pairs: Father Ocean × Der Lagi, Father Ocean × With You.
3. **After merge**, fold the set WAV into the owed `storage.py` cache-eviction sweep (below).

## Verification evidence (which checks ran, what they returned)

- **Backend:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **415 passed in ~62s** (was 409; +6 in `tests/test_set_route.py`).
- **Web:** `npm run typecheck` → PASS (clean); `npm test` → **49 passed (8 files)** (was 45; +4 net across the rewritten Play/App/Export tests + Setup multi-set tests).
- **`/set` route tests specifically:** `pytest tests/test_set_route.py -q` → **6 passed** (real 2-pair render+join; the ≤2 cap → 400; an off-tempo pair declined with a reason; the not-analyzed guard → 409; bad-id → 404; cache hit → 200).
- **Live end-to-end (running app, real catalog audio, zero cloud):** `POST /set` for Father Ocean × Der Lagi + Father Ocean × With You → ready in ~24s; manifest: both kept, **seam_at 442.63s (7:22)**, **duration 900.324s (15:00)**; `GET /set/{id}/audio` → `206 audio/wav`, total **158,817,284 bytes (~151 MB)**, range-capable. Drove the real UI: built the same two-set, landed on the stripped Play screen (line-up shows Set 1 NOW / Set 2 UP NEXT, no Parts/chips/type box), pressed play → **clock advanced 0:29→0:31**, one `/set/…/audio` request. Then paused.
- **Git:** committed `319d507` on `feat/multiset-ui`; pushed to `origin`; `git status` clean except pre-existing Windows LF↔CRLF line-ending noise on files this session did NOT edit (excluded from the commit on purpose).

## Open escalations / RE-VERIFY next session (claims, not settled facts)

- **The multi-set feature is NOT merged.** It lives only on `feat/multiset-ui` (pushed). The MVP on `main` is unaffected. A PR is one click from being opened (link above); merging is the founder's call after the ear-listen.
- **CLAIM to re-verify — the engine was not touched.** `render.py` / `validate.py` / `set_render.py` are dangerous surfaces; this feature only _imports and calls_ them. Re-verify by re-running the backend suite (415 green at handoff) — the golden gate + set-render tests would catch any accidental behavior change.
- **Dangerous test-harness files were edited** (`App.test.tsx`, `PlayScreen.test.tsx`, `PlayScreen.loading.test.tsx`, `ExportScreen.test.tsx`, `SetupScreen.test.tsx`) via the confirm-and-apply flow (founder approved twice this session; approvals recorded + cleared). Each keeps every prior check and adds multi-set coverage; **no test was weakened** — re-verify by reading the diffs if in doubt.
- **File size / disk (pre-launch):** a two-set of long tracks is ~**150 MB**; the two-set cap bounds it, but the `storage.py` **cache-eviction sweep is still owed** and now also orphans a new file kind (`*.set.wav`), on top of the m6.5+chain mix WAVs. Land before the ~50-user test.
- **Live steering retirement is a PRODUCT decision, not a bug.** The backend `/live/*` routes still exist and pass their tests; they're just no longer called by the UI. If the founder ever wants steering back, it's a re-wire, not a rebuild.
- **`gh` (GitHub CLI) is not installed** on this machine, and no API token is in the environment — so a PR can only be opened via the web link (above) until `gh` is set up. (git push works via the `manager` credential helper.)
- **Still open from before (unchanged):** CORS must be set to the real origin before public exposure; no public/hosted deployment exists yet; the ~50-creator validation test is the real finish line.
