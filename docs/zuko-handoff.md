# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-05 — **Rule 4 (Regenerate variety) is DONE and DEPLOYED LIVE on `main`: a real tempo-synced DELAY echo + reverb bed, at the founder-chosen boldest level. Every mix now renders with the echo.** This session also adopted the working rule that made it fast: **prototype the SOUND in a throwaway script and get ear-approval BEFORE the production build.** Moving on from Rule 4.

## Where things stand (one breath)

- **Rule 4 is LIVE on `main`** (merged + pushed, commit `250e059`/`684f295`): `plan._RULE4_ENABLED = True`, `render._DELAY_ECHO_WET = 1.10` (the boldest level the founder chose). `ENGINE_VERSION` = **`m6.11+m8echo`** — the mix + set caches auto-invalidated, so every mix now re-renders with the echo. **Fully reversible:** flip `_RULE4_ENABLED` back to `False` and it drops to `m6.11` (byte-identical to pre-Rule-4; golden gate still passes as the fallback).
- **Rule 4 = a REAL echo (a tempo-synced feedback DELAY, 1/4-note, feedback 0.55, wet 1.10) on the vocal + the continuous reverb bed.** Founder ear-approved the sound (prototype `d_quarter_long`) then chose the boldest LEVEL after A/B-ing louder variants on two real pairs (Innerbloom×Dooriyan, Father Ocean×Der Lagi Lekin). The real engine reproduces the approved sound (0.993 correlation at the base level); passes plan + finished-audio referee, no clip.
- **How we got there (the productive part):** three earlier Rule-4 shapes were rejected BY EAR — a chop-and-repeat re-fire, a "forceful" gap-sized echo, and a phrase-tail STAMP (which is chop/stutter, not an echo). Once we prototyped the actual sound (throwaway scripts → dated Desktop folders → founder listens → change a number → re-render in minutes), it converged in one sitting. **This is now a standing rule (memory: `prototype-sound-before-ceremony`).**
- **The approved delay echo replaced the earlier gap-echo engine** (deleted `_gap_echo`/`_voiced_runs`/`_gap_echo_events`/`_duck_bed_under_echoes`/`_GAP_ECHO_*` and its tests). The **breath-safe re-fire helper is still parked** intact in `workers/rule3_parked.py` for a future Rule 3.

## In flight — honest state

- **Nothing in flight. Rule 4 is DONE and DEPLOYED** to `main` (`_RULE4_ENABLED=True`, `_DELAY_ECHO_WET=1.10`), pushed. The design branch `design/mix-reverse-engineering` was also merged to `main` via GitHub PR #5 (the OFF version) and then the deploy commits merged on top. Verified live: `ENGINE_VERSION` = `m6.11+m8echo`, `rule4_enabled()` = True.
- **Consequence to expect:** because `ENGINE_VERSION` changed, every existing mix/set cache is invalidated — all mixes re-render (compute cost) and any mix a user already had now sounds different (has the echo). This is intended and reversible.
- **Suite:** 499 passed / 1 failed on the last full run — the 1 failure is the **pre-existing, unrelated `test_cache_sweep.py` flake** (see open items), NOT Rule 4.

## Do first next session

1. **Rule 4 is done — move on.** No follow-up owed unless the founder wants the boldest echo level re-tuned by ear on more catalog pairs (the adversarial reviewer noted it's safe but "loud is a taste call"; the founder chose it on two real pairs and said deploy).
2. **Fix the pre-existing `test_cache_sweep.py` flake** (cross-file pollution from `test_mix_route.py`) — has a task chip; unrelated to Rule 4.
3. **Optional cleanup:** delete the dormant, now-superseded effect-pool subsystem (Rule 4's branch pre-empts it; the pool tests now turn Rule 4 off to run). Founder's call.

## Verification evidence

- **Full backend suite (Rule 4 LIVE), 2026-08-05:** `pytest -q` (from `services/api`) → **499 passed, 1 failed.** The 1 failure = `test_cache_sweep.py::test_dry_run_reports_but_deletes_nothing`, the known order-dependent flake (passes in isolation; reproduces only as the pair `test_mix_route.py test_cache_sweep.py`). Not Rule 4.
- **Golden byte-identical-OFF gate:** still **passes** with the flag on — flipping `_RULE4_ENABLED` back to `False` returns the exact pre-Rule-4 engine (`m6.11`). The OFF path is a proven, one-line fallback.
- **Live engine smoke check:** `ENGINE_VERSION == "m6.11+m8echo"` and `plan.rule4_enabled() is True` on `main`.
- **Real renders (flag ON):** Innerbloom×Dooriyan and Father Ocean×Der Lagi Lekin both passed plan + finished-audio referee, peak 0.891 (no clip), at echo levels up to wet 1.10 (echo ≈ −4.4 dB vs the vocal).
- **Ceremony (two adversarial passes + independent test-author):**
  - Build pass: test-author wrote 11 hermetic tests (no bugs); adversarial reviewer **`safe` for the OFF ship** (byte-identical-OFF, containment, level/clip refuted, determinism); found **echo-length inflation** → **FIXED** (tail bounded to audible decay).
  - **Deploy pass (LIVE at wet 1.10):** adversarial reviewer verdict **`safe` to deploy** — the joint `_max_wet_gain` trim guarantees echo+reverb ≤ +2.5 dB over the dry (a fixed 0.5 dB margin under the +3 dB P2 guard, **independent of `wet`**), so a louder echo **cannot clip or fail a render** (empirically: peak +2.50 dB at the ceiling, never above, `g` never 0); crest rises (mush guard can't fire); caches invalidate correctly. Residuals are TASTE (loudness) + the expected re-render cost, not safety.
- **A real bug the golden gate caught mid-build:** the Rule-4 knobs first collided (`_ECHO_FEEDBACK`) with the legacy produced-drop echo constant, silently changing the OFF path → renamed to `_DELAY_ECHO_*`; golden byte-identity restored. (The safety net worked.)

## Open escalations / re-verify next session (claims, not facts)

- **DANGEROUS surfaces on this branch vs `main` — RE-VERIFY before trusting "OFF == main":** `workers/render.py` (delay echo, this session), and from earlier superseded-but-committed work on this branch: `services/api/app/planner/validate.py` (removed `_throw_violations`), `models.py` (removed `Placement.throws`), `plan.py`, `mix.py`. All ship OFF; re-confirm `_RULE4_ENABLED`/`_EFFECT_POOL_ENABLED` are both `False` and the golden gate passes at the start of next session.
- **Rule 4 activation DONE (was a dangerous change) — re-verify the LIVE state next session:** confirm `_RULE4_ENABLED is True`, `_DELAY_ECHO_WET == 1.10`, `ENGINE_VERSION == "m6.11+m8echo"` on `main`, and that the golden gate still passes (so the OFF fallback is intact). The deploy passed a dedicated adversarial `safe` verdict at the live level; the ON path has an integration test (`test_render.py::test_rule4_on_render_*`).
- **Pre-existing flaky test (NOT Rule 4):** the full suite can intermittently fail ONE `test_cache_sweep.py` test — proven cross-file state pollution from `test_mix_route.py` (both untouched by this work; each passes in isolation; reproduces as the 2-file pair `test_mix_route.py test_cache_sweep.py`). Spun off as its own task chip.
- **Founder decision pending:** whether to delete the dormant, now-superseded effect-pool subsystem (Rule 4 pre-empts it).
- **Older open item (carried, re-verify):** the Export screen "Download full mix" defect from the 2026-07-21 handoff — not touched; status unknown.
- **Listening artefacts on the founder's Desktop (throwaway):** `Prompt-DJ Rule4 PROTOTYPE real echo (2026-08-05)` (the approved `d_quarter_long` + variants), `Prompt-DJ Rule4 PROTOTYPE beat-grid echo (2026-08-05)` (rejected chop versions), `Prompt-DJ Rule4 gap-echo listening (2026-08-05)` (rejected gap-echo).
