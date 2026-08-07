# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

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
