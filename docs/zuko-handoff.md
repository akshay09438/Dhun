# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-07 — **The FOUR-RULE product is BUILT and internally verified, on a feature branch (NOT merged to `main`).** This session took Rule 3 (chop & repeat) from a throwaway ear-approved harness all the way into real engine code and wired the app so a user **picks a rule per song** (Simple / Chop & repeat / Echo), on the shared BPM+key foundation, with best-parts + set-transitions common to every rule. Rule 4 became a distinct pick (dry default, echo on Rule 4). The app runs locally end-to-end. **Nothing merged; `main` unchanged.** The next real step is the founder's **final product testing** on the running app, then the merge PR (which is also where the functional/technical spec bodies get their full Rule-3/4 sections — the spec headers already carry a dated banner).

## Where things stand (one breath)

- **Rule 3 (chop & repeat) — BUILT into the app.** Two NEW, non-guarded modules: `services/api/app/planner/rule3.py` (the deterministic chop-schedule "brain" — A tease / C full-sentence blocks from the curated `hooks.py` hook or a founder timestamp; cut on the vocal's own downbeats; word-safe word-ends; trade in the beat's instrumental gaps; weave A/C on the grid) and `workers/rule3.py` (the renderer — beat-locked per-bar warp, word-safe fade endings, Rule-4 echo+reverb tails, trade). It **REUSES `workers/render.py`'s primitives by import, so `render.py` is UNTOUCHED.** Wired into `routes/mix.py::_run_mix` behind a per-mix `rule` field.
- **Rule 4 (echo+reverb) — now a distinct PICK.** `build_mix_plan(rule=…)` sets the `reverb_bed` echo trigger **only when `rule==4`** (planner-only change; `render.py` untouched). The **default mix is now DRY** (was always-echo since the 2026-08-05 deploy). `_ENGINE_VERSION_BASE` bumped `m9band15`→`m11rule` so stale echo-default mixes re-render under the gate.
- **Best-parts + set transitions — COMMON to every rule** (founder correction). The best-parts highlight crop and the set seam engine (`workers/best_parts.py`, `workers/set_render.py`) apply to Rule 3/4 exactly as to Rule 1 — a set joins finished, best-parts-cropped mixes and reads only rule-independent metadata. **Verified: a Rule-3 mix serves its 189 s highlight, not the 476 s full render.**
- **Set builder — per-song rule selection.** `SetPairRequest.rule` threads through `set_id_for`/`_run_set` (each song renders under its rule; the tempo/mixability reconciliation stays rule-independent). Web: a per-song **"HOW IT PLAYS"** picker (Simple / Chop & repeat / Echo) in `SetupScreen`, threaded `App → study.ts → makeSet/makeMix → api.ts`.
- **Shared foundation intact.** BPM stretch + key match + fence-decline run first for every rule; Rule 3/4 inherit them.
- **Rule 2 — reserved, deliberately NOT built** (founder's call).
- **Docs:** `docs/RULEBOOK.md` (finalized, canonical rule design) written this session; functional/technical spec headers carry a dated 2026-08-07 banner; the implementation-plan status + drift log are current.

## In flight — honest state

- **Nothing is half-coded.** All the Rule-3/4 + set-builder code is complete and tested; the suite is GREEN (evidence below). The only "in flight" is that it lives on a **feature branch, un-merged** — awaiting the founder's final ear/UX testing on the running app before the merge PR.
- **Deferred to the merge PR (deliberate, per our doc discipline):** the FULL Rule-3/4 + set-picker sections in the _bodies_ of `functional-spec.md` / `technical-spec.md` (they currently carry an accurate dated banner at the top + point to `RULEBOOK.md`).

## Do first next session

1. **Founder final testing on the running app** (API on :8000, web on :5173 — `.claude/launch.json` configs `backend` + `web`). Build a Chop mix, an Echo mix, and a two-song set that mixes rules; confirm each plays the best-parts highlight and the set transitions land. Fix anything the ear flags.
2. **Then open the merge PR** for the Rule-3/4 + set-builder branch → `main`, updating the functional/technical spec bodies in that same PR.
3. **Small open product choices** (non-blocking): the How-Deep hook lead-in (A starts 59.8 s vs exactly 61 s); the Rule-3 default density (medium vs sparse). Both are one-line tweaks once the founder decides by ear.

## Verification evidence

- **Full backend suite:** `cd services/api && .venv/Scripts/python.exe -m pytest -q` → **536 passed, 1 warning in 176 s** (the warning is a Windows file-lock ResourceWarning during a threaded test's temp-file cleanup — the test itself passed; not a failure).
- **New Rule-3 tests (part of the 536):** `test_rule3_planner.py` (6 hermetic — phrases, word-end-stops-at-boundary, A-short/C-full, auto A+B→C, trade-vs-whole-track, schedule-on-downbeats-in-gaps) + `test_rule3_render.py` (1 integration — real ffmpeg DSP on synthetic audio → valid non-silent correct-length WAV with the 220 Hz chop present at its scheduled downbeats, absent in the bed gaps). All green.
- **Web:** `npm run typecheck --workspace apps/web` → clean (tsc no errors); `npm test --workspace apps/web` → **49 passed (8 files)**.
- **End-to-end (manual, this session):** a Rule-3 mix rendered through the live `_run_mix` (476 s render, serves a 189 s best-parts highlight, plan persisted `rule=3`); Rule-4 gating confirmed (rule 1 → no `reverb_bed`, rule 4 → `reverb_bed=True`); a **mixed-rule set** (song 1 = Rule 3, song 2 = Rule 4) rendered & joined — both kept, one 362 s set, seam at 173 s.
- **The app is running locally right now** (backend + web dev servers up; no backend errors in the logs; the web Setup screen renders with the new "HOW IT PLAYS" picker, confirmed via the page's accessibility tree).

## Open escalations / re-verify next session (claims, not facts)

- **NO dangerous-surface files were edited this session** — `render.py`, `validate.py`, `routes/songs.py`, `storage.py`, config/settings, `.github/**`, `conftest.py`, `*.test.ts/tsx`, `vitest.config`, `pytest.ini` are all **untouched** (Rule 3 reuses `render.py`'s functions by import; the quality guard `validate.assert_render` guards every rule's output by CALL, not by change). **RE-VERIFY next session** with `git diff --stat main...HEAD` that the changed set is only: `app/planner/rule3.py`, `workers/rule3.py`, `app/routes/mix.py`, `app/routes/set.py`, `app/planner/plan.py`, `app/models.py`, `tests/test_rule3_*.py`, `tests/test_mix_route.py`, the web files, and docs — nothing on the dangerous list.
- **Default sound changed dry (was echo).** Gating Rule 4 made the default mix DRY; the engine-version bump invalidates old echo-default caches so they re-render. Founder-approved (dry default, echo on Rule 4). Re-confirm by ear during final testing that a plain "Simple" mix sounds right without echo.
- **Rule-3 best-parts crop** uses Rule 1's crop logic (Song-1 grid + vocal regions), which doesn't know about the chops — it crops to a sensible Song-1 highlight window containing whatever chops fall there. Works and is defensive (falls back to the full mix on any crop error), but a chop-aware crop is a possible future refinement — **ear-check the Rule-3 highlight during final testing.**
- **Carried from before (unchanged this session):** Change ①/② (BPM+key) are LIVE on `main`; the pre-existing `test_cache_sweep.py` disk/order flake; the M6 backlog (short-clip export, loudness master) and the ~50-creator validation test remain the V1 finish line.
