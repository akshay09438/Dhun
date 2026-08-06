# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-06 — **Two production features built from the key+BPM prototype. Change ① (BPM band widening) is MERGED and LIVE on `main`. Change ② (KEY matching) is BUILT + fully tested + pushed to a branch with a PR open — but NOT merged and NOT fully re-cleared: two adversarial reviews found two issues, both FIXED, but the re-review of the fixes did not finish (session usage limit). Do not merge ② until the fixes are re-reviewed.**

## Where things stand (one breath)

- **Change ① — BPM band ±11% → ±15%: DONE, MERGED, LIVE on `main`** (merge `af90618`, feat commit `db666c9`). `fence.SAFE_STRETCH_LO/HI` = 0.85/1.15, `WARP_LO/HI` = 0.81/1.19; `workers/set_render.py` now IMPORTS the band from fence (single source of truth); `_ENGINE_VERSION_BASE` = `m9band15`. Two independent adversarial reviews returned SAFE; monotonicity proven (widening only adds pairs). Recovers ~15 more catalog pairs. Fully reversible.
- **Change ② — KEY matching: BUILT + tested + pushed, PR OPEN, NOT MERGED.** Branch `feat/key-matching` (commit `00e9f33`, 18 files). Shifts Song 2's vocal into a compatible key (fuzzy Camelot, cap ±2) before the mix, via a local Signalsmith Stretch helper (MIT). Verified (two independent renders must agree), content-addressed cache (song-id + shift + formant + HELPER_VERSION), LOUD failure (crash/hang/non-determinism → the mix declines visibly). Confidence gate skips the 5 flagged songs. Ships behind an instant off-switch (`_KEY_MATCH_ENABLED`, folded into ENGINE_VERSION `+m10key`). PR: https://github.com/akshay09438/Dhun/pull/new/feat/key-matching

## In flight — honest state (Change ②)

- **The suite is GREEN** (529 passed — see evidence). The feature works end-to-end (verified below). But it is **NOT cleared to merge**, for two reasons:
  1. **Two review findings were FIXED but the fix RE-REVIEW did not complete** (both reviewer agents died on the session usage limit, resets ~2:40pm Asia/Calcutta). The fixes are tested-green but not independently re-cleared.
     - _Finding A (Reviewer 1):_ the retired live "Play" vocal-bus path (`routes/live.py`) served an UN-shifted vocal. **It is DEAD CODE** — the web `fetchVocalBus` has no callers, no LiveMix component is mounted, so the shipped Play screen plays the finished (key-matched) Download mix. Fixed anyway (defense-in-depth): `_run_vocal_bus` now applies the same shift so it can never emit an un-shifted "key-matched" vocal.
     - _Finding B (Reviewer 2):_ rule K1 could mis-judge a CHROMA-FLAT vocal (false-reject a valid pair, or false-pass a wrong one). Fixed with a "decisive-disagreement" rule: `validate.assert_key_shift` declines only when the chroma DECISIVELY reads a different rotation (`corrs[best] - corrs[claimed] > 0.15`); on inconclusive/flat material it trusts the verified helper. New deterministic tests cover both halves.
  2. **The living docs are only PARTIALLY updated for ②** — the implementation-plan drift log has an entry (below), but `technical-spec.md`/`functional-spec.md` were not fully revised for key-matching. Finish next session.

## Do first next session

1. **Re-run the two adversarial reviewers on the Change ② FIXES** (the K1 decisive-disagreement rule in `validate.py` + the live-bus consistency fix in `routes/live.py`). If BOTH return safe → proceed; if not → address before merge.
2. **Finish the Change ② docs**: update `technical-spec.md` (the pitch stage is retired / GPL rubberband gone; key-matching added) and `functional-spec.md` (clashing pairs now auto key-match) to mirror the code.
3. **Then the founder reviews the PR and decides on merge.** Nothing merges before he looks.
4. Resolve the flagged residuals with the founder (see escalations).

## Verification evidence

- **Full backend suite (Change ② branch):** `cd services/api && .venv/Scripts/python.exe -m pytest -q` → **529 passed in 157s** (last run). The known pre-existing `test_cache_sweep.py` order-dependent flake did NOT fire this run.
- **render.py GPL-pitch deletion — GOLDEN byte-identical:** a live-path mix (I Adore You × Der Lagi, SHIPPED_CHAIN + effect_variety on) rendered BEFORE and AFTER the `_pitch_shift` deletion produced the identical hash `ec40e83787c9da016a935ec1b7d22660f278b5abb7a6b513bc585d723b2d9694` (37,767,212 bytes). Live-path `vocal_moves` pitch = `[0.0, 0.0, 0.0]` (the stage was provably dead). Deleting dead code changed nothing.
- **Change ② end-to-end (real `_run_mix`):** Innerbloom (beat 6B) × Don't Start Now (vocal 10B) → decision `+1 st` → verified+cached Signalsmith shift → K1 referee passed → **job READY**, 101 MB mix WAV written, `.pitchshift.wav` cache created. Flagged pair Anchor Point × Don't Start Now → `shift 0` (gated, logged). Loud-failure path: a transient helper failure declined visibly (job `("error", "Couldn't key-match…")`, no WAV, no cache) — never a silently un-shifted mix.
- **Change ① on `main`:** band reads `0.85/1.15` in `fence.py`; merged `af90618`.

## Open escalations / re-verify next session (claims, not facts)

- **Change ② is NOT cleared to merge** — the fix re-review is incomplete (session limit). Re-run it first.
- **Dangerous-surface claims to RE-VERIFY (Change ②, on the branch):** (a) `render.py` — the GPL `_pitch_shift` is gone and the golden mix is byte-identical (verified TODAY, treat as a claim); (b) `validate.py` — the K1 chroma referee is additive (R1/R3/B3/R6/R7 untouched) and catches stable-but-wrong; (c) `storage.py` — `.pitchshift.wav` is evictable AND the sweep still cannot touch catalog/stems/analyses.
- **CI does not run pytest** (`.github/workflows/ci.yml` runs vitest only) — so ALL the Change ② safety tests run only locally, not automatically. Real assurance gap for a dangerous change; recommend a pytest CI job (small, separate change; touches a dangerous workflow file).
- **Anchor Point gating tension** — it is in the 5 gated `KEY_UNTRUSTED_SONG_IDS`, but it was in a founder-approved demo. Confirm whether gating it (shift 0) is intended for now.
- **Pitch helper = Signalsmith WASM in a local headless Chromium** (validation-grade; "swap for a native binding before scale"). Every key-matched pair launches Chromium once per (song, shift), then caches. Confirm the render machine has a working Chromium/Edge or every shift silently declines. Minor: a helper TIMEOUT can orphan a Chromium process on Windows (resource leak) — add a process-tree kill.
- **Carried, older:** the Export screen "Download full mix" defect (2026-07-21) — diagnosed, NOT fixed. And the pre-existing `test_cache_sweep.py` order-dependent flake (its own task chip).

## Prototype artefacts (throwaway, on the founder's Desktop)

- `Prompt-DJ KEY+BPM PROTOTYPE (2026-08-06)` — the key/BPM listening sets + MORNING_REPORT + staged production plan.
- `Prompt-DJ FULL DEMO MIXES (2026-08-06)` — the two full key+BPM demo mixes the founder ear-approved.
