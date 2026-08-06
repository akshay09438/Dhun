# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-06 (later session) — **The key+BPM production effort is COMPLETE and LIVE on `main`. Both Change ① (wider tempo band) and Change ② (auto key-matching) are merged.** Change ②'s two review findings were fixed, the fixes were re-reviewed clear, one extra defense-in-depth hardening landed, the living docs were finished, and PR #7 was merged by the founder (merge `5612042`). The merged branch `feat/key-matching` has been deleted (local + remote). Nothing is in flight. **The next real work is M6 — starting with the broken "Download full mix" button.**

## Where things stand (one breath)

- **Change ① — BPM band ±11% → ±15%: MERGED, LIVE** (merge `af90618`). `fence.SAFE_STRETCH_LO/HI` = 0.85/1.15, `WARP_LO/HI` = 0.81/1.19; `validate.py` and `workers/set_render.py` import the band from `fence` (one source of truth); `_ENGINE_VERSION_BASE` = `m9band15`. Monotonic (widening only adds pairs); two independent reviews SAFE. Recovers ~15 catalog pairs. Reversible.
- **Change ② — auto key-matching: MERGED, LIVE** (PR #7, merge `5612042`; feature `00e9f33`, hardening `c66976f`, docs `9ab88ec`). When Song 2's vocal clashes in key with Song 1's beat, the app shifts the vocal into a compatible key (fuzzy Camelot, cap ±2 st) BEFORE the mix, via a local MIT **Signalsmith** helper run as a **Node subprocess** (`app/audio/pitch_helper/bridge.mjs` — NOT headless Chromium; earlier notes said Chromium, the code is a Node subprocess). Three layers: DECISION (`app/planner/keys.py`, confidence gate + 5 gated songs), EXECUTOR (`app/audio/pitch.py`, two independent renders must agree, content-addressed cache, `PitchError` = loud decline), REFEREE **K1** (`app/planner/validate.py` + `app/audio/chroma.py`, independently re-derives the shipped vocal's chroma; declines only on decisive disagreement). Off-switch `mix.py._KEY_MATCH_ENABLED` folded into `ENGINE_VERSION +m10key` (flip off → byte-identical to pre-②). The retired live "Play" vocal-bus path (dead code) also applies the shift AND K1, so it can never emit an un-shifted/unverified vocal if re-enabled.

## In flight — honest state

- **Nothing in flight.** The key+BPM work is fully closed out (built, reviewed, merged, documented, branch cleaned). The tree is clean on `main`, in sync with `origin/main`.

## Do first next session

1. **Fix the broken "Download full mix" button** (highest value — a finished mix can't currently leave the machine except by an operator copying the `.wav` by hand). Diagnosed 2026-07-21, NOT fixed: the fetched blob is discarded ~2 ms after download and the link is never attached to the page; a silent fetch failure looks identical. The proper fix also means strengthening `ExportScreen.test.tsx` (a dangerous-surface test file), which is why it waited on a founder go. Use `/zuko:fix` or `/zuko:build`.
2. **The rest of M6:** short-clip (15–30s) export (a hero output, still to build) + loudness master / limiter.
3. **Housekeeping:** add a pytest CI job (today `.github/workflows/ci.yml` runs vitest only, so ALL the Python safety tests — including K1/key — run locally, not automatically); the `0.15` K1-margin ear-check on a genuinely flat/breathy vocal; confirm the Anchor Point gating decision; confirm the render host has Node (else every key-shift silently declines) + add a process-tree kill so a helper timeout can't orphan a process on Windows; clear the chronic C: disk pressure.
4. **Then the ~50-creator validation test** — the V1 finish line.

## Verification evidence

- **Change ② merge:** PR #7 merged to `main` (`5612042`); `git merge-base --is-ancestor` confirms `00e9f33`, `c66976f`, `9ab88ec` are all on `origin/main`; local `main` fast-forwarded, 0/0 with `origin/main`, tree clean.
- **Backend suite (on the branch before merge):** `cd services/api && .venv/Scripts/python.exe -m pytest -q` → **528 passed, 1 failed**; the 1 failure is the KNOWN pre-existing `test_cache_sweep.py` order/disk-dependent flake (it fails on a _different_ test in isolation and the log shows `evicted ALL … still only reached 0.00 GB free` — the machine's C: is genuinely full; unrelated to the change).
- **Live-path hardening (`c66976f`):** after adding `validate.assert_key_shift` to `routes/live.py._run_vocal_bus`, targeted `test_live_route.py + test_validate.py + test_mix_route.py` → **86 passed**; `import app.routes.live; import app.routes.mix` → no cycle.
- **Re-review of the two ② fixes (2026-08-06):** two independent adversarial reviewers. **K1 (`validate.py`): both PROCEED/SAFE** — sign math verified for ±1/±2, the only chroma-flat false-pass cases are harmonically neutral, K1 confirmed wired into `_run_mix` before render, declines loud. **Live-bus:** reviewers split — R1 PROCEED (dead code, re-verified: nothing mounts `LiveMix`/`liveAudio`), R2 flagged a latent hole (live path applied the shift but skipped K1) → founder chose to close it → hardened in `c66976f`.

## Open escalations / re-verify next session (claims, not facts)

- **Dangerous-surface claims to RE-VERIFY (now on `main`):** (a) `validate.py` — the K1 chroma referee is ADDITIVE (R1/R3/B3/R6/R7 untouched) and catches stable-but-wrong; (b) `workers/render.py` — the GPL `_pitch_shift` is DELETED and a live-path golden mix was byte-identical before/after (hash `ec40e837…`); a nonzero `pitch_semitones` now RAISES; (c) `storage.py` — `.pitchshift.wav` is on the eviction allowlist AND the sweep still cannot touch catalog/stems/analyses.
- **CI does not run pytest** — the whole Python safety net (K1, key gate, render guard) runs only locally. Real assurance gap; a small pytest CI job is recommended (touches a dangerous workflow file).
- **Anchor Point gating tension** — it is in the 5 gated `KEY_UNTRUSTED_SONG_IDS` (Anchor Point, Dooriyan, Rapture, Wari Jawa, With You) but was in a founder-approved demo. Confirm gating it (shift 0) is intended; remove its id once its key is ear-checked.
- **Pitch helper = Node/Signalsmith subprocess** (validation-grade; swap for a native binding before scale). Confirm the render host has `node`; a helper TIMEOUT can orphan a process on Windows — add a process-tree kill.
- **`_K1_MIN_MARGIN = 0.15`** is an untuned taste constant; its "inconclusive → trust the helper" branch is only exercised via a mocked `best_rotation`. Ear-check on a flat/breathy vocal someday (not a blocker).
- **Carried, older — the Export "Download full mix" defect (2026-07-21)** is now the #1 next job (see Do first). And the pre-existing `test_cache_sweep.py` disk/order-dependent flake (its own task chip).

## Prototype artefacts (throwaway, on the founder's Desktop)

- `Prompt-DJ KEY+BPM PROTOTYPE (2026-08-06)` — the key/BPM listening sets + MORNING_REPORT + staged production plan.
- `Prompt-DJ FULL DEMO MIXES (2026-08-06)` — the two full key+BPM demo mixes the founder ear-approved.
