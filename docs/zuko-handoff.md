# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-14 (**MVP FEATURE-COMPLETE AND MERGED TO MAIN — all 5 features built. This session: turned the vocal chain ON, fixed the vocal hand-off, locked down CORS, cleared ~3.9 GB cache, wired pitch repair (Slice 2d, gated OFF), built silent set-order scoring — then the founder MERGED it all to `main` (PR #1).** Suite at merge: 409 backend + 40 web green. ✅ **Verified `origin/main` HEAD = `5e446f3` "Merge pull request #1"; `SHIPPED_CHAIN` + `set_score.py` + `pitch_repair_enabled` all present on main.** The earlier "175 commits behind" escalation is RESOLVED — everything is on main now.)

## Where things stand (one breath)

All five V1 features are now BUILT: (1) two-song DJ mix, (2) live steering + regenerate, (3) **pitch repair — wired but shipped OFF**, (4) the vocal-polish chain — **ON**, ear-confirmed ("sounds plain" fixed), (5) **silent set-order scoring — done**. The vocal chain is live in the app, the vocal hand-off is now a guaranteed crossfade (no two-full-leads on any pair), CORS is locked down for public exposure, and pitch repair can nudge a clashing-key vocal into key but is OFF because the current catalog has nothing for it to fix. **All of it is now MERGED to `main`** (PR #1, `5e446f3`). The MVP is complete on the default branch. What is NOT done: a public/hosted deployment (the app only runs locally on the founder's machine — there is no shareable web URL yet) and the ~50-creator validation test.

## In flight - done vs left

- **Nothing is half-built or red.** 409 backend + 40 web green, golden gate byte-identical.
- **DONE + committed this session (branch `feat/mvp-finish-pitch-scoring`, on top of the earlier `feat/house-bollywood-energy-sync` work):**
  - Earlier in the session (also on the branch, `a989586`..`29dd7e0`): vocal chain turned ON (`SHIPPED_CHAIN`, m6.5), Play-screen buffering pill, chain guard test, R1 hand-off fade fix (`render.py`, m6.6, adversarially reviewed SAFE, ear-confirmed), CORS lockdown (`config.py`), ~3.9 GB regenerable-mix cache cleared, docs aligned.
  - `d5177e5` — **BUILD 1: pitch repair (Slice 2d) WIRED, gated OFF.** `build_mix_plan` computes the camelot shift + emits it; new `VocalChainConfig.pitch_repair_enabled` (default False); clash beyond ±cap DECLINES; P1 (±3) + `_pitch_shift` (formant=preserved) untouched. `scripts/tune_pitch.py` ear-test tool (zero cloud).
  - `64458c2` — **BUILD 2: silent set-order scoring.** `workers/set_score.py` + a guarded hook in `build_set.py`; logs app-pick vs user-pick to `data/set_order_log.csv` (gitignored); changes nothing users hear.
- **DECISION (founder): pitch_repair_enabled stays OFF.** Measured: of the 10 pickable catalog pairs, 8 are already key-compatible and 2 clash beyond ±3 (would decline: Father Ocean × With You, I Adore You × Tere Bina) — **zero pairs pitch repair could actually fix**. Turning it on would only _remove_ Father Ocean × With You. The 3 named clashing pairs (FO×Suniyan, Anchor×Maula Mere, Innerbloom×Dooriyan) are **dropbox/test-only, not in the live catalog**. Leave OFF until a clashing-but-close song is added (a one-line flip).
- **Left:** M6 the ~50-creator validation test; the pre-launch storage.py cache-eviction _sweep_ (still owed before the user test); the in-app set builder (a parked discovery item, memory `promptdj-inapp-set-builder`).

## Do first next session

1. **The MVP is merged to `main` (PR #1, `5e446f3`) — no merge action left.** Start local `main` up to date: `git checkout main && git pull`. (This session's work happened on `feat/mvp-finish-pitch-scoring`; it's fully merged.)
2. **The real finish line is the ~50-creator VALIDATION TEST (M6)** — the app is feature-complete but unproven with real users. That needs (a) a way for testers to reach it — a **public/hosted deployment** (none exists yet; today it only runs locally on the founder's machine), and (b) the pre-launch owed items below (CORS origin set, cache-eviction sweep).
3. Optional next feature: the in-app **set builder** (parked discovery item, memory `promptdj-inapp-set-builder`) — take it into `/zuko:discover` first.

## Verification evidence (which checks ran, what they returned)

- **Backend:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **409 passed in ~57s.**
- **Golden gate + pitch-decline + set-score:** `pytest tests/test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0 tests/test_plan.py::test_pitch_repair_declines_a_pair_beyond_the_safe_band tests/test_set_score.py` → **6 passed** (disabled render still byte-identical to m6.0; >±3 declines; scoring logs both picks).
- **Web:** `npm run typecheck` → PASS; `npm test` → **40 passed (8 files).**
- **Zero-cloud proven:** pitch ear-test (`tune_pitch.py`) + set-score both ran on cached analyses with Replicate guarded to raise; no cloud calls. The 3 pitch pairs + all set demos rendered locally.
- **✅ MERGE VERIFIED:** `git fetch` then `git show origin/main:services/api/app/routes/mix.py | grep -c SHIPPED_CHAIN` → **3** (was 0 before the merge); `set_score.py` present on main; `origin/main` HEAD = `5e446f3` "Merge pull request #1". The branch is 0 commits ahead of `origin/main`. `git status` clean.

## Open escalations / RE-VERIFY next session (claims, not settled facts)

- **The MVP is merged to `main` and complete — but there is NO public deployment.** The app only runs locally (dev servers on `localhost:5173`/`:8000`); there is no shareable/hosted URL. A real validation test (or any outside user) needs a deploy first — that work is not started.
- **`pitch_repair_enabled` is False and should STAY false** until a clashing-but-repairable song is added (there is no live job today). Flipping it is a deliberate founder call (ear + yes), like the chain enable; on `enabled` it is on the danger list.
- **🔴 `render.py` + `validate.py` (dangerous surfaces) carry the ENABLED vocal chain AND the R1 hand-off fade.** CLAIM to re-verify: golden gate proves the DISABLED path is still byte-identical to m6.0 (`test_golden_enabled_false_is_byte_identical_to_m6_0`, green at handoff). The enabled chain + hand-off fade are ear-confirmed + adversarially reviewed SAFE, but re-run the golden gate before trusting the disabled/fallback path.
- **CORS is now env-gated** (`config.py`): default allows only `localhost:5173`; production must set `PROMPTDJ_CORS_ORIGINS`; dev wildcard needs `PROMPTDJ_DEV_CORS=1`. Verify the deploy sets the real origin before public exposure.
- **"I Adore You" catalog beat is LOCAL-ONLY** (gitignored manifest) — won't transfer to another machine/branch; not a committed catalog member.
- **Pre-launch owed:** the `storage.py` cache-eviction sweep (unbounded disk; this session cleared once by hand but there's no automatic sweep) — land before the ~50-user test.
