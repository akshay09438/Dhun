# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-08 (session close) — **EVERYTHING MERGED TO `main` AND VERIFIED GREEN.** Two GitHub PRs landed on `main`: **#9** (the automatic-rule-assignment + set/tempo/vocal fixes, formerly branch `feat/randomized-rule-assignment`) and **#10** (the NEW internal **dev app** / ops dashboard, formerly branch `feat/dev-ops-dashboard`, which was stacked on #9). `main` is now `43e8929`; local `main` is fast-forwarded and in sync with `origin/main`; working tree clean.

**Naming set this session (use these):** **"dev app"** = the internal developer/ops dashboard at `/#dev`; **"dj user app"** = the regular DJ console end users use. (They are ONE web app, two entrances: `/` for users, `/#dev` for the team.)

**What shipped this session (the dev app, PR #10):** a read-only ops dashboard that records **every mix/set outcome** to a tiny SQLite event log (`services/api/app/events.py` → `data/events.db`, gitignored) via non-fatal hooks in `_run_mix`/`_run_set`; a read-only API (`routes/admin.py`: `/admin/summary|events|devices|retention`, behind an optional `PROMPTDJ_DASHBOARD_TOKEN` gate); and the web `AdminScreen` (reached by a `#dev` hash gate in `main.tsx`) showing a health strip, a newest-first paged feed with red/amber/green health + the engine's own "what to do" note on degraded mixes + ▶ play + the mixing style per mix, a **by-device** rollup, and **device-level retention** (returning vs new, first/last-seen dates — counts persistent browsers, not verified people, until login). No render/validate/storage/config engine file was touched; the only dangerous-surface edit was the new `AdminScreen.test.tsx`, added via the founder-approved `.zuko/approve.js` flow (approvals cleared after landing).

### DO FIRST NEXT SESSION

- **Founder ear-test on the running `main`.** Both the rule-assignment work AND the dev app are now live on `main` — the rule-assignment ear-test the founder wanted now happens on `main`. If anything sounds off, fix forward on `main` (via a branch + PR, never direct).
- **To see the dev app with real data:** run the app from `main`, make a mix in the dj user app, then open `http://localhost:5173/#dev`. (The event log starts empty — the session's 2 demo mixes were wiped.)

### In flight — honest state

- **Nothing is half-coded or uncommitted.** All feature work is merged to `main` and green. This handoff + the doc freshness fixes ("not merged" → "merged") are on branch `docs/handoff-2026-08-08` (docs only), pending its own small PR.

### Verification evidence (this session, on the merged `main` @ `43e8929`)

- **Backend:** `cd services/api && .venv/Scripts/python.exe -m pytest -q -p no:randomly` → **619 passed** (~3:42).
- **Web:** `npm run typecheck` → clean; `npm run lint` → clean; `npm test` → **65 passed** (9 files).
- **Live end-to-end demo:** started the app from the merged code on spare ports, made **2 real mixes through the actual `/mix` route** (Father Ocean × Der Lagi, I Adore You × Dooriyan) → both recorded in the event log and shown in the live `/#dev` dashboard with real anomaly detail (`suspicious_beat_vocal` ~99%, `key_measured` +3 st) and playable audio. Demo `events.db` wiped afterward.
- **New dev-app tests (all green):** `test_events.py` (17), `test_admin_route.py` (9), `test_events_integration.py` (2), `AdminScreen.test.tsx` (13).

### Open escalations / re-verify next session (claims, not facts)

- **DEV APP SECURITY — re-verify before ANY internet deploy.** The `/#dev` dashboard exposes user content (the songs each device mixed). It is **open on localhost** and safe there, but it MUST have `PROMPTDJ_DASHBOARD_TOKEN` set (a shared secret) before it is served at any internet-reachable URL — otherwise it is an unauthenticated user-data endpoint. The gate is built and tested (`test_admin_route.py`), but "is the token actually set in the deployed env?" is a human/deploy-time check, not something code review can prove.
- **Deferred by design (cheap to add later — the event log already carries a plain `user_id` column):** real logins/usernames and TRUE per-person retention & cohorts. The current retention is honest but DEVICE-level (a persistent browser tag), so it is directional, not a headcount of people.
- **Pre-existing flake carried:** `test_cache_sweep.py` (order/timing-dependent on Windows; it exercises `storage.py`, a dangerous surface — diagnose before any "fix").

---

### Earlier — 2026-08-07 (session close) — **COMMITTED + PUSHED to GitHub (branch `feat/randomized-rule-assignment`, commit `b8a776f`), NOT yet merged to `main`.** _(Superseded — this branch is now MERGED to `main` as PR #9; see the 2026-08-08 entry above.)_ `main` is untouched; the branch is on `origin` and local↔origin are in sync (0 ahead / 0 behind), working tree clean. **The whole session's work is in that one commit:** (1) AUTOMATIC RULE ASSIGNMENT — the three manual rule buttons are gone; each generation's mixing style is auto-assigned by a deterministic shuffler (`app/planner/rule_shuffle.py`) and shown as a label; ONE shared engine, two callers — single-mix re-roll (up to **5** a sitting, was 2) and a **set of up to 5 mixes** (was 2), each mix auto-styled by its position; founder-confirmed the "keep dealing" algorithm + "auto-assign sets too". (2) The four fixes below (never-decline in sets, backend anomaly reporting, the R1/beat-vocal fix, set-cap→5 docs). **Verification (this session, on the committed code): full backend 591 passed; web 52 passed; typecheck + lint clean.** App runs locally (API :8000, web :5173).

### DO FIRST NEXT SESSION

- **Founder ear-test on the running app, then merge.** Nothing is merged to `main` yet. The founder wanted to test locally first. Once they're happy, the remaining step is to **open the PR and merge `feat/randomized-rule-assignment` into `main`** (GitHub offered the PR link on push: `https://github.com/akshay09438/Dhun/pull/new/feat/randomized-rule-assignment`). Do NOT merge without the founder's go-ahead.
- Concretely worth an ear-check: (a) "I Adore You" as a beat now sings its lyrics in the gaps; (b) Rapture × Uff Teri Ada builds (Rapture music-only); (c) a far-apart pair in a SET (e.g. Innerbloom × Jugni Ji) is forced onto the beat, not skipped; (d) the auto-assigned style label + "another take" up to 5; (e) a set of up to 5 mixes.

### In flight — honest state (session close)

- **Nothing is half-coded or uncommitted.** The entire session is in commit `b8a776f`, pushed to `origin/feat/randomized-rule-assignment`; `git status` is clean and local↔origin are in sync (0/0). `main` is untouched — the branch is **NOT merged** (awaiting the founder's ear-test + go-ahead to open the PR / merge).

### Verification evidence (this session, on the committed code)

- **Backend:** `cd services/api && .venv/Scripts/python.exe -m pytest -q -p no:randomly` → **591 passed** (~4 min).
- **Web:** `npm run typecheck` → clean; `npm run lint` → clean; `npm test` → **52 passed** (8 files).
- **New/changed tests:** `test_rule_shuffle.py` (22), `test_anomaly.py` (6), `test_instrumental_beats.py` (6, rewritten to hand-list-only), `test_set_route.py` (+ never-decline + auto-rule), `test_mix_route.py` (+ auto-rule), `App.test.tsx`/`SetupScreen.test.tsx` (auto-rule UI, edited under the `.zuko/approve.js` flow).
- **Real-data checks (in-process):** "I Adore You" sings (s1_vocal_regions = 4 gaps, validate PASSES); Rapture music-only (s1_vocal_regions `[]`, validate PASSES); a far-apart SET pair (122×95) forced onto the beat and kept.

### Fixes this session (same branch, on top of the auto-rule work)

- **R1 "vocals overlap beyond a crossfade" skip fixed (Rapture × Uff Teri Ada) — via a HAND-LIST, not an auto-rule.** Root cause: Rapture's vocal STEM is instrumental bleed the separator mis-heard as singing, so its analysis reads one whole-song vocal region; weaving that false "vocal" overlapped Song 2 → R1 skipped it. Fix: **Rapture added to the hand-picked `INSTRUMENTAL_ONLY_BEATS` list** (founder's ear: no real lyrics). `is_instrumental_only(a1)` checks ONLY that list — beats sing by default. `vocal_coverage()` feeds ONLY the backend anomaly (`suspicious_beat_vocal`), never silences. ⚠️ HISTORY: an intermediate fix auto-silenced any beat reading ≥90% vocal — it wrongly muted 'I Adore You' (real vocals, reads 99%); the founder caught it and it was REMOVED (a silencing rule must be a human/ear call, not the app's guess). Verified: I Adore You sings (4 gaps, validate PASSES); Rapture music-only (validate PASSES). `test_instrumental_beats.py` rewritten.
- **Set cap unified to 5 in the docs (founder: "only 5 sets, the core rule").** Purged "up to two / caps at two" from the functional spec + CLAUDE.md non-goals + plan; the rule is `MAX_MIXES_PER_SET = 5` (a single MIX is still one beat + one vocal — that's unchanged). The "still only 2 in the app" the founder saw was a STALE dev server (no preview was running; the on-disk web code is correct at 5) — a hard refresh / dev-server restart shows 5.

- **Never-decline now applies in SETS (founder point 1).** `routes/set.py`'s mixability gate was calling the fence WITHOUT `force_tempo`, so a set silently dropped far-apart members ("too far apart in tempo (~28% stretch)") even though the single-mix path forces the same pair. Fixed: the gate now passes `force_tempo=force_tempo_enabled()`. The two production callers (mix + set) are consistent; the only mixability decline left anywhere is a no-beat track. Reproduced + guarded by `test_set_route.py::test_set_NEVER_declines_a_far_tempo_pair_it_forces_it_onto_the_beat` (122×95 → forced, kept). _(The Set 5 "Rapture × Uff Teri Ada" skip was a DIFFERENT thing — those are only ~11% apart, so tempo was never the issue; it hit the R1 "no two lead voices at once" quality guard. Not a tempo bug; a separate arrangement/quality question the founder is still weighing.)_
- **Backend anomaly reporting (founder point 2).** New `app/planner/anomaly.py` — the mix pipeline still generates from imperfect inputs but now logs a structured "what was unexpected + what to do" per degraded condition (forced stretch, low-confidence beat grid, key measured from audio because the label was untrusted). Wired into `_run_mix`; reporting only, never changes a mix. `test_anomaly.py` (5). **The running backend must be restarted to serve the set fix** (uvicorn has no --reload here).

### Where THIS change stands (one breath)

- **The engine** — `app/planner/rule_shuffle.py`. Core `rule_at_from_seed(seed, position)` (deck of the 6 orderings, seeded per cycle by sha256, seam-arranged so no style repeats back-to-back anywhere). Two thin callers: `rule_for(user, s1, s2, n)` (single-pair re-roll) and `rule_for_set(user, set_index, position)` (set). The single-pair output is **byte-identical to the earlier-approved version** (a golden vector pins it). Tests: `tests/test_rule_shuffle.py` (22).
- **Single-mix wiring** — `routes/mix.py`: `MixRequest` gains optional `user_id`+`generation`; `_resolve_rule_take` computes rule via the shuffler and `take = generation+1`. The `mix_id_for` FORMULA is untouched (rule was always in it). Frontend: buttons removed from `SetupScreen`; `App.tsx` tracks a per-browser id (`lib/user.ts`) + a generation counter, caps at `MAX_GENERATIONS_PER_SESSION=5`; `PlayScreen` shows a "Mix style · …" badge + "take N of 5".
- **Set wiring** — `routes/set.py`: `SetRequest` gains optional `user_id`+`set_index`; `_resolve_pairs` auto-assigns each mix's rule; `MAX_SETS` renamed/raised to `MAX_MIXES_PER_SET=5`; `SetMember.rule` returned for display. Frontend: `takeNextSetIndex()` (monotonic per-browser), `SetupScreen` allows up to 5 mixes, `PlayScreen` shows each mix's style in the line-up. Tests: `tests/test_set_route.py` (+2).
- **Protected test files** — `App.test.tsx` + `SetupScreen.test.tsx` were edited under the founder-approved `.zuko/approve.js` flow (additive UI tests + the cap-at-5 update; no test weakened). Approvals recorded then **cleared** after landing.
- **The "3 styles only" ceiling** is a silent code contract (founder chose no UI mention); the per-result style label is the visible variety.

### Re-verify next session (claims, not facts)

- **`test_cache_sweep.py` is a PRE-EXISTING FLAKE** (order/timing-dependent on Windows — failed once in a full run, passed alone + on repeats). `git diff main -- app/storage.py workers/ tests/test_cache_sweep.py` is EMPTY, so this change cannot be the cause. Worth a future harden (it tests `storage.py`, a dangerous surface — diagnose first).
- **Cache keying choice to confirm by ear/UX:** a re-roll uses `take = generation+1`, so every "another take" is a fresh render slot even when the style recurs (founder chose "fresh take each press"). Whether a recurring style _sounds_ different depends on within-rule variety (Rule 4 echo moments, Rule 3 chop choice) — mostly unshipped; flagged as the follow-on.
- **5-mix sets cost:** the set cap was 2 to keep render time + WAV size down. It's now 5 in ONE constant each side (`MAX_MIXES_PER_SET`) — dial back if a 5-mix set (≈5 renders + a long WAV) is too heavy for validation.

### Original 2026-08-07 (MERGED to `main`) status below

2026-08-07 — **SHIPPED: new base rules for Rule 1/3/4 are MERGED to `main` (@ `b7e5501`) and PUSHED.** Two founder-mandated rules now sit under every mix: **(1) never decline any pair** — a far-apart vocal is stretched fully onto the beat and per-bar beat-locked so it can't drift; **(2) measure the key from the audio** when the detected key label can't be trusted (common on real uploads), instead of shipping an un-shifted clash. This resolved "Rapture × Jugni sounds like two songs" (root cause = a key clash both flagged labels hid). Built during a goodnight run on `feat/auto-match-keymatch`, then founder-approved (the one protected-file change applied via the approval flow), the switch flipped on, and merged to `main`. **The app runs locally and end-to-end on the merged code (API :8000, web :5173).**

## Where things stand (one breath)

- **Empirical key-match (LIVE).** `app/audio/chroma.py` adds `empirical_shift` (AutoMashUpper cosine over beat-sync chroma, reusing the existing `chroma()`); `routes/mix.py` calls it as the fallback whenever `keys.resolve_key_shift` returns a "key-skip" (untrusted label). ±3 semitones, formant-preserved via the Signalsmith executor. For Rapture × Jugni it measures **+3 st → 9A (Rapture's exact key)**, cos 0.907 vs 0.855 unshifted. `ENGINE_VERSION` bumped `m11rule`→`m12match` so stale un-shifted mixes re-render.
- **Never-decline tempo auto-match (LIVE, ON).** `fence.legal_options(force_tempo=True)` forces a far-apart pair instead of declining: beat native (master), vocal stretched fully (`tempo_forced`), per-bar beat-locked with the widened `WARP_*_FORCED` grip; `_fold_source` folds all octaves so the forced stretch is provably in `[FORCE_STRETCH_LO=0.69, FORCE_STRETCH_HI=1.45]` for ANY pair. `plan._FORCE_TEMPO_ENABLED = True` (folded into `ENGINE_VERSION` as `+m12force`). The ONLY remaining decline is a track with no beat grid at all.
- **Validator (protected file) — APPLIED, founder-approved.** `planner/validate.py` widens the B3 stretch band + R7 warp band **only for a `tempo_forced` plan** (every other guard — clipping, single-vocal R1, on-downbeat R3, key K1 — unchanged), plus a single-segment-drift guard so a forced section that fails to beat-lock is rejected, never shipped off-beat. Approval recorded in `.zuko/approvals.json` / `.zuko/goodnight/applied.json`.
- **Chop/Echo balance (LIVE).** `workers/rule3.py`: beat full + vocal subtle + a touch more reverb (`_DUCK` −3→−1 dB, `_CHOP_GAIN` 1.10→0.90, `_WET` 0.40→0.55) — Chop & Echo only, not Simple (founder call). **Ear-tunable; founder heard the direction, not a final A/B.**
- **Beat-sensor health (LIVE).** `planner/beatgrid.py` + a per-mix log: downbeat regularity + BPM/grid agreement, so a mis-detected grid is visible. Rapture & Jugni both read healthy (~0.99).
- **Sets already keep every member** (cut across far tempos, blend within) — so "every song is made" holds for sets too; no set-path change was needed.

## In flight — honest state

- **Nothing is half-coded.** Everything above is complete, applied, and on `main`. Working tree has only spurious LF↔CRLF line-ending churn on 5 web files (`git diff --ignore-all-space` is empty — no real content change); left uncommitted on purpose.

## Do first next session

1. **Founder ear-tuning of the Chop & Echo balance** on the running app — confirm "beat full + vocal subtle" sounds right across a few pairs, or nudge `workers/rule3.py`'s three dials.
2. **Rule-4 (Echo) balance — attended build.** Needs `render.py` (protected) + the founder's ear for a real vocal-level dial; PARKED from the goodnight run on purpose.
3. **Deeper beat-detection** — the founder chose "harden + verify" (done); a from-scratch detector rebuild is its own future project.
4. Still owed before the ~50-user test (carried): loudness master + short-clip export polish, the `storage.py` cache-eviction sweep.

## Verification evidence

- **Full backend suite:** `cd services/api && .venv/Scripts/python.exe -m pytest -q` → **554 passed (~2:10)** on the merged `main`. (Was 536 before this work; +18 = 5 chroma + 5 beatgrid + 7 forced-tempo + net test updates for the removed "decline far-apart" behaviour.)
- **New tests:** `test_chroma_match.py` (matcher scoring, pure), `test_beatgrid.py` (grid-health), `test_forced_tempo.py` (octave-fold bounds, never-decline, forced band, beat-lock multi-segment). Updated `test_plan.py`/`test_mix_route.py` to the new intent (far-apart FORCES; only a no-grid track declines).
- **Live end-to-end:** `Rapture × Jugni` — a pair the app used to refuse — rendered through the LIVE `_run_mix` on all three rules (`tempo_forced=True`, master 120, vocal_stretch 1.2632, +3 key-match); the real applied `validate.py` accepted the forced plan (12 beat-locked segments, 0 violations).
- **Adversarial safety review** of the validator change: verdict `not-proven-safe` (correct — it's a relaxation gated on `tempo_forced`); its fixable findings (octave-fold bound, engine-version fold-in, zero tests, single-segment drift) were all fixed/tested/guarded before merge.
- **Web:** no frontend files were edited this session; last known green = 49 web tests + typecheck clean.
- **Git:** `main` @ `b7e5501`, `0 0` vs `origin/main` (fully synced/pushed).

## Open escalations / re-verify next session (claims, not facts)

- **`validate.py` was edited (a dangerous surface).** RE-VERIFY next session with `git show b7e5501 -- services/api/app/planner/validate.py` (and the `f313c6d`/`1c7fa55` commits) that the ONLY change is the `tempo_forced`-gated band widening + the single-segment-drift guard — a normal (non-forced) plan must still be judged byte-identically. The adversarial review confirmed this at merge time; re-confirm it still holds.
- **The forced full-match is a QUALITY relaxation.** For a product whose worst outcome is a bad-sounding mix, the wider band is only ear-validated on Rapture × Jugni so far. As more far-apart pairs get tried, keep an ear on whether any forced stretch near the ±41% fold-max warbles; the referee proves on-beat, not "sounds good."
- **Chop/Echo balance** is direction-approved, not final-A/B-approved — treat the current dials as a starting point, re-confirm by ear.
- **Carried:** the `storage.py` cache-eviction sweep (disk pressure) and the M6 backlog (loudness master, short-clip export) remain the V1 finish line before the ~50-creator validation test.
