# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-11 (**Vocal-timing arc CLOSED + tuning week STARTED.** This session: wired all five catalog hooks (m6.3), diagnosed and fixed the vocal-timing bug (m6.4 beat-lock truncate — Tujhe late-by-2-beats fixed, Der Lagi proven NOT a bug), parked the auto-crop for good, built a CLI set builder with a sandbox vocal-chain A/B, added a second catalog beat (LOCAL-ONLY), and began the Phase-0 vocal-chain tuning (`saturate_wet=0.3` approved, 6 dials to go). **Suite: 396 backend green (fresh at handoff).** All on `feat/house-bollywood-energy-sync`, **NOT merged, NOT pushed.** `render.py`/`validate.py`/`vocal_regions`/`lead_sections`/`enabled`/Slice 2d ALL untouched.)

## Where things stand (one breath)

Both V1 features are built + founder-confirmed (offline DJ mix + live steering). This session was quality + tooling on top: **every catalog vocal mix now lands its real hand-marked hook** on the drop (m6.3, all five donors), and **vocals no longer un-snap from the beat on a mis-detected bar** (m6.4 — the "Tujhe enters a beat late" bug, root-caused on the isolated vocal bus and fixed by truncating the beat-lock at a glitch instead of bailing; Der Lagi's "early" turned out to be Father Ocean's own vocal, not a bug). The **auto-crop is parked for good** (it can't make a valid mix — R1 vocal overlap — so full-length is the hero). A **CLI set builder** (`scripts/build_set.py`) lets the founder hear beat-matched sets by ear (no in-app /set screen, by choice), and its new `--chain` flag drives the **vocal-chain tuning week**, which is now **in flight** (chain still ships OFF; tuned per-render in a sandbox; `saturate_wet=0.3` approved).

## In flight - done vs left

- **Nothing is half-built or red.** Every commit is green and safe-surface-only or a dev tool.
- **DONE + committed this session (6 commits, `47930d3`..`38ffae5`):**
  - `47930d3` — **m6.3 hooks:** all five catalog vocal donors given hand-marked hooks (from the founder's ~1hr marking session). Every catalog vocal mix re-renders with its real signature line; Der Lagi's baseline corrected.
  - `ebedbbc` — banked the set-seam demo + drop-accuracy / crop-readiness diagnostics (read-only tools).
  - `6ba9356` — **crop PARKED for good** (R1 vocal-overlap in the tight window; full-length is the MVP) + the framing note that the 2026-07-09 single-mix rejection didn't settle the set-crop question.
  - `dd8c4e3` — **CLI set builder** (`build_set.py`): renders a continuous beat-matched set to a WAV; one-tempo reconciliation + outlier decline; zero-cloud.
  - `4fdffc5` — **m6.4 beat-lock truncate fix** (the vocal-timing bug). `fence.warp_map` truncates at a glitch bar (locks up to it, trailing global segment for the rest) instead of bailing — the entry snaps to the beat. Planner-only; `render.py`/`validate.py` untouched; both glitch-bail tests rewritten.
  - `38ffae5` — **`build_set.py --chain`:** sandbox vocal-chain A/B for sets (dials in the filename; renders to `data/tuning_renders/`, never the cache).
- **IN FLIGHT — the vocal-chain tuning week (the main open thread):** the nine-stage chain still ships `enabled=False`. The founder is tuning it per-render in the sandbox. **Approved so far: `saturate_wet=0.3` (dial 1 of 7).** Order: saturate_wet → presence_gain_db → reverb_wet → duck_depth_db → compress_ratio → highpass_hz → deess_intensity.
- **LOCAL-ONLY (NOT in git):** "I Adore You" added as a second catalog **beat** (`data/library/manifest.json`, which is **gitignored**). Provisional — the founder heard its Tujhe mix pre-fix (that's how the bug surfaced); needs a post-fix re-hear + a keep/remove decision.
- **Left / still parked (from before):** Slice 2d (pitch repair) — a gated engine with **no decision logic** (pitch pinned 0; nothing pitch-corrects today); flipping `enabled=True` after tuning (a deliberate founder call). Thread A (align the vocal to the audible syllable vs the downbeat) — **no proven bug demands it**, deferred.

## Do first next session

1. **Continue the vocal-chain tuning.** Next dial: `presence_gain_db` (default 2.5, safe ±6), holding `saturate_wet=0.3`. Sets: `build_set.py --set "..." --set "..." --chain --dials "saturate_wet=0.3 presence_gain_db=X" --out "set.wav"` vs the OFF baseline (same command, no `--chain`). Single pairs: `scripts/tune_chain.py`. **Do NOT turn dials for the founder — they drive; you run their values.** Carry every approved dial forward.
2. **Decide "I Adore You" in/out of the catalog.** It's local-only + provisional. Re-render `I Adore You × Tujhe` (now m6.4, timing-fixed), founder ear-checks, then keep or remove the manifest entry.
3. **When all 7 dials are approved:** record the winning config; then flipping `enabled=True` is a **separate, deliberate, dangerous-surface** decision (confirm-and-apply flow + a live ear-check).

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **396 passed in ~55s.**
- **Golden gate + Gate B explicit:** `pytest tests/test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0 tests/test_plan.py::test_gate_b_plan_determinism_on_a_fixed_analysis` → **2 passed** (disabled render byte-identical to m6.0; plan-determinism holds).
- **`git status` → clean.** 6 commits this session (`47930d3`..`38ffae5`); `ENGINE_VERSION = "m6.4"`. **NOT pushed, NOT merged.**
- **Catalog manifest is gitignored** — verified `git check-ignore services/api/data/library/manifest.json` (ignored) and `git ls-files` (not tracked). The "I Adore You" addition is local-only.
- **Vocal-chain "enabling needs no render.py change" — verified:** `tune_chain.py` + `build_set.py --chain` enable via `build_mix_plan(chain=VocalChainConfig(enabled=True))` + unchanged `render_mix`; the chain is built and gated on `plan.vocal_moves`.
- **Web suite: NOT run** — no web/TS files touched this session (build_set / tune_chain are Python CLIs; no /set UI built). Last known 39 web green.

## Open escalations / RE-VERIFY next session (claims, not settled facts)

- **🔴 `render.py` + `validate.py` (dangerous surfaces) still carry the DISABLED Phase-0 vocal chain. UNTOUCHED this session.** CLAIM to re-verify: the golden gate proves disabled == m6.0 byte-for-byte — re-run `test_golden_enabled_false_is_byte_identical_to_m6_0` before trusting it (green at this handoff). The **ENABLED** chain path is being TUNED now (sandbox only, OFF in the shipped app) and is **not-proven-safe-to-ship** until the founder finishes tuning and does a live ear-check.
- **`enabled` is FALSE and must STAY false** until the founder flips it after tuning. Flipping it is a **dangerous-surface change** (`enabled` is on the danger list) → the confirm-and-apply flow, not a drift.
- **"I Adore You" catalog addition is LOCAL-ONLY (gitignored) + provisional.** A different machine/session will NOT have it. Not founder-confirmed post-fix.
- **Branch not merged / not pushed.** The whole arc lives on `feat/house-bollywood-energy-sync`; a merge needs the standard pre-merge review (and the still-owed R1-crossfade-relaxation adversarial re-verify noted in `technical-spec.md`).
- **Slice 2d (pitch repair) parked** — a gated engine with no decision logic; `rubberband` (GPL) is never called at mix time (pitch pinned 0).
- **Working preference recorded (memory):** for audio/engine bugs the founder wants read-only root-cause diagnosis with hard audio-measured numbers before any fix, and rejects magic-offset/nudge band-aids (`memory/promptdj-diagnose-before-fix.md`).
