# Zuko handoff - Prompt-DJ

_The single source of truth for "where things stand" between sessions. `/handoff` rewrites this at the end of a session; `/start` and the SessionStart hook replay it at the beginning. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-07-10 (**PHASE 0 — the vocal chain — is BUILT and shipped DISABLED; the "fix the ears" diagnostic work is DONE. Everything is committed on branch `feat/house-bollywood-energy-sync`, NOT merged to main. Suite: 384 backend green (fresh run at handoff). The founder is in the tuning week — enabling the chain in the `C:\DJ-AI-Experiment` sandbox and turning dials by ear; that is his work, not a code task.**)

## Where things stand (one breath)

Phase 0 turned the mixer from a _placement_ engine into a _production_ engine — a nine-stage vocal chain (de-ess → high-pass → pitch → stretch → compress → saturate → presence EQ → reverb → bed-duck) plus referee rules P1–P5, **all shipped OFF** (`VocalChainConfig.enabled=False`). A golden-file gate proves the disabled render is **byte-identical to the pre-Phase-0 `m6.0` baseline** (verified on real audio). Slice 1 also switched the app to the **loved rules arrangement** by default (the disliked AI arranger is gated off). Then, working around the founder's tuning week (different files), a diagnostic pass ("fix the ears") **killed four theories with measurement** and dropped the ~23%-accurate **section map** out of the decision path — the app now decides from measured energy + hand-marked hooks, not a guess.

## In flight — done vs left

- **Nothing is half-built or red.** Every slice below is committed, tests green, and either shipped-disabled or behaviour-neutral.
- **Phase 0 Slices 1, 2a, 2b, 2c: DONE, chain shipped DISABLED.** Nine stages + referee P1–P5 built; golden gate green; independent adversarial review returned **SAFE for the disabled ship** (8 attack vectors held). Close-out refinements done: reverb IR L2-normalized (song-independent `reverb_wet`), a **crest-factor mush backstop**, the level/crest guards in a standalone `workers/chain_guards.py`, duck envelope confirmed smoothed. FFmpeg pinned (`8.1.1`, fails loudly on drift). Tuning harness ready: `scripts/tune_chain.py` + `docs/tuning-guide.md`.
- **The GPL question: DECIDED — keep it.** The FFmpeg build is GPL (`--enable-librubberband`); the founder chose to stay on it (server-side MVP, GPL triggers on distribution not use). Exit plan written in `docs/ffmpeg.md`. Revisit only if on-device rendering ever ships.
- **"Fix the ears": DONE.** Analysis cache split (cloud by `song_id`, local by `LOCAL_ANALYSIS_VERSION`, zero-cloud proven). Section map **dropped** from the decision path (`ENGINE_VERSION m6.1`) — measured 23% precise, and it was already influencing zero catalog mixes. Gate B added. Diagnostics recorded in the drift log (entries 31–33).
- **Left / next (all AFTER the founder's tuning week):** flip `enabled=True` (founder decision, in the sandbox first); **Slice 2d** (pitch repair — turn `fence.py` from bouncer to repairman, `compute_pitch_repair` is written-not-called); then the carried-forward M6 (loudness master + short-clip export) and the ~50-creator test.

## Do first next session

1. **Ask the founder where the tuning week landed.** The winning dial positions become the first `bollywood_vocal_over_house` recipe. If he has numbers, wire them as the default `VocalChainConfig` and prep the `enabled=True` flip (in the sandbox first, confirm by ear).
2. **Before enabling:** the two must-fixes are already built (GPL decided; crest-mush backstop in). Re-confirm the golden gate is green and re-read `docs/tuning-guide.md` (exclude the 3 key-clashing pairs from tuning; keep them as the Slice 2d evidence set).
3. **Whatever the founder wants next** — do risky/audible work in the `C:\DJ-AI-Experiment` sandbox first, ear-confirm, then port.

## Verification evidence (which checks ran, what they returned)

- **Ran fresh at handoff:** `cd services/api && ./.venv/Scripts/python.exe -m pytest -q` → **384 passed in ~64s.** (Includes: golden gate `test_golden_enabled_false_is_byte_identical_to_m6_0` + determinism; referee P1–P5; chain-guard synthetic tests; ffmpeg-pin; reverb linearity; Gate B; the section-map-out evidence test; the zero-cloud re-analysis test.)
- **`git status` → clean.** Latest commit `a671c6c` (section map dropped, m6.1). 8 commits this arc, all on `feat/house-bollywood-energy-sync`.
- **Zero cloud proven** for the engine/analysis bumps (stems/analysis keyed by `song_id`; diagnostics built 56 plans with `replicate.run` rigged to crash — none fired).
- **Web suite:** not run this session (no web/TS files touched; last known 39 web green).

## Open escalations / RE-VERIFY next session (claims, not settled facts)

- **Dangerous surfaces `workers/render.py` + `services/api/app/planner/validate.py`** carry the Phase-0 vocal chain + referee P1–P5, **shipped DISABLED**. CLAIM to re-verify: the golden gate proves disabled == `m6.0` byte-for-byte — **re-run `test_golden_enabled_false_is_byte_identical_to_m6_0` next session** before trusting it. Independent adversarial review said SAFE _for the disabled ship_; the ENABLED path is _not-proven-safe_ until the tuning week + a live ear-check.
- **`enabled` is FALSE and must STAY false** until the founder explicitly flips it after tuning. **Do not enable it.** Slice 2d (pitch repair) is parked — pitch is pinned to 0 in the planner, so `rubberband` (GPL) is never called at mix time today.
- **Branch not merged to main.** The whole Phase-0 arc lives on `feat/house-bollywood-energy-sync`. A merge would need the standard pre-merge review (and the still-owed R1-crossfade-relaxation adversarial re-verify noted in `technical-spec.md` "Known follow-ups").
- **The founder is tuning against `render.py`.** Do NOT change `render.py`/`validate.py` under his feet — a change there invalidates his ear-time.
