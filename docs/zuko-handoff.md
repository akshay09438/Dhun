# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-05 — **Rule 4 (Regenerate variety) is FINALLY nailed: a real tempo-synced DELAY echo + reverb bed, FOUNDER EAR-APPROVED, built into the real engine with full ceremony, ships OFF. Nothing merged to `main`.** This session also adopted a new working rule that made it fast: **prototype the SOUND in a throwaway script and get ear-approval BEFORE the production build.**

## Where things stand (one breath)

- **`main` is untouched.** All work is on branch `design/mix-reverse-engineering` (pushed to `origin`). Rule 4 ships **OFF** behind `plan._RULE4_ENABLED = False`; with it off the render is **byte-identical to `main`** (golden gate verified this session). `ENGINE_VERSION` = `m6.11` when off.
- **Rule 4 = a REAL echo (a tempo-synced feedback DELAY) on the vocal + the continuous reverb bed.** Founder ear-approved the sound (prototype variant `d_quarter_long`: **1/4-note delay, feedback 0.55, wet 0.45**). The real engine (`render_mix`, flag ON) reproduces that approved prototype at **0.993 full-mix correlation**, passes the plan + finished-audio referee, peak 0.891 (no clip).
- **How we got there (the productive part):** three earlier Rule-4 shapes were rejected BY EAR — a chop-and-repeat re-fire, a "forceful" gap-sized echo, and a phrase-tail STAMP (which is chop/stutter, not an echo). Once we prototyped the actual sound (throwaway scripts → dated Desktop folders → founder listens → change a number → re-render in minutes), it converged in one sitting. **This is now a standing rule (memory: `prototype-sound-before-ceremony`).**
- **The approved delay echo replaced the earlier gap-echo engine** (deleted `_gap_echo`/`_voiced_runs`/`_gap_echo_events`/`_duck_bed_under_echoes`/`_GAP_ECHO_*` and its tests). The **breath-safe re-fire helper is still parked** intact in `workers/rule3_parked.py` for a future Rule 3.

## In flight — honest state

- **Nothing half-done in the code.** Rule 4 is complete, committed (`b6ef52e`), pushed, ceremony-passed, ships OFF. The remaining step is a **human decision**, not code: flip `_RULE4_ENABLED` to `True` to turn it on for real.
- **The PR was NOT opened** — `gh` (GitHub CLI) is not installed on this machine. The branch is pushed; open the PR at `https://github.com/akshay09438/Dhun/pull/new/design/mix-reverse-engineering` (or just flip the flag + merge as the founder prefers — the catalog work earlier merged without a PR at his request).
- **Suite is GREEN** (see evidence). One **pre-existing, unrelated flaky test** exists — see open items.

## Do first next session

1. **Founder ear-confirm the codebase render** (a WAV was sent this session — `services/api/data/listening/…` was cleaned up; re-render via `render_mix` flag-ON if needed). It measured 0.993 identical to the approved prototype, so this is a formality.
2. **Flip `_RULE4_ENABLED = True`** when the founder says go. That is a dangerous-surface activation of a user-facing audio path — re-run the adversarial review at that point (the reviewer explicitly gated its `safe` verdict to the OFF ship only). The ON path now HAS an integration test (`test_render.py::test_rule4_on_render_*`), which it previously lacked.
3. **Decide whether to also delete the dormant effect-pool subsystem** (superseded, still shipping OFF behind `_EFFECT_POOL_ENABLED=False`). Out of scope this session; flagged for a clean-up call.

## Verification evidence

- **Full backend suite, 2026-08-05:** `pytest -q` (from `services/api`) → **500 passed in ~201 s.** (The pre-existing `test_cache_sweep.py` flake did NOT surface this run — it is order-dependent, so it can still appear; see open items.)
- **Affected subset (re-run several times):** `pytest tests/test_echo.py tests/test_echo_independent.py tests/test_render.py tests/test_plan.py tests/test_validate.py tests/test_rule3_parked.py tests/test_effect_pool_dsp.py tests/test_effect_pool_referee.py tests/test_mix_route.py -q` → **236 passed.**
- **Golden byte-identical-OFF gate:** `test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0` **passes** → flags-off render == `main`. `ENGINE_VERSION` prints `m6.11` with the flag off.
- **Real render (flag ON), iadoreyou × tujhe:** `validate_plan`/`validate_render` = no violations; peak 0.891; **0.993 full-mix correlation to the approved prototype `d_quarter_long`.**
- **Ceremony:** founder ear-approval + `.zuko/approve.js` file approval recorded/cleared on `render.py` (each burst); independent **test-author** wrote 11 hermetic tests (no bugs; pinned the approved constants); independent **adversarial reviewer** verdict **`safe` for the OFF ship** — byte-identical-OFF held, containment (Song-1 R1) held, level/clip attack REFUTED empirically (crest rises; peak +1–2 dB), determinism held, no dead refs. It found **echo-length inflation** (a placement carried trailing silence past the audible echo) → **FIXED** (tail bounded to the audible decay via `_DELAY_ECHO_DECAY_TAPS`); re-verified the sound unchanged at 0.993.
- **A real bug the golden gate caught mid-build:** the new Rule-4 knobs were first named `_ECHO_*` and one (`_ECHO_FEEDBACK`) **collided** with the legacy produced-drop echo constant, silently changing the OFF path. Renamed to `_DELAY_ECHO_*`; golden byte-identity restored. (The safety net worked.)

## Open escalations / re-verify next session (claims, not facts)

- **DANGEROUS surfaces on this branch vs `main` — RE-VERIFY before trusting "OFF == main":** `workers/render.py` (delay echo, this session), and from earlier superseded-but-committed work on this branch: `services/api/app/planner/validate.py` (removed `_throw_violations`), `models.py` (removed `Placement.throws`), `plan.py`, `mix.py`. All ship OFF; re-confirm `_RULE4_ENABLED`/`_EFFECT_POOL_ENABLED` are both `False` and the golden gate passes at the start of next session.
- **Activation is its own dangerous change.** The adversarial `safe` verdict covers ONLY the OFF ship. Flipping `_RULE4_ENABLED` ON activates a user-facing audio path → re-run the review (now backed by the ON integration test).
- **Pre-existing flaky test (NOT Rule 4):** the full suite can intermittently fail ONE `test_cache_sweep.py` test — proven cross-file state pollution from `test_mix_route.py` (both untouched by this work; each passes in isolation; reproduces as the 2-file pair `test_mix_route.py test_cache_sweep.py`). Spun off as its own task chip. It did not fire in this session's full run, but it is latent.
- **Founder decision pending:** (a) flip Rule 4 on; (b) whether to delete the dormant effect-pool subsystem.
- **Older open item (carried, re-verify):** the Export screen "Download full mix" defect from the 2026-07-21 handoff — not touched; status unknown.
- **Listening artefacts on the founder's Desktop (throwaway):** `Prompt-DJ Rule4 PROTOTYPE real echo (2026-08-05)` (the approved `d_quarter_long` + variants), `Prompt-DJ Rule4 PROTOTYPE beat-grid echo (2026-08-05)` (rejected chop versions), `Prompt-DJ Rule4 gap-echo listening (2026-08-05)` (rejected gap-echo).
