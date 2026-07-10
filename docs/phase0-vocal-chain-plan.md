# Phase 0 — The Vocal Chain: build plan

_Working plan for the PRD at `phase0_prd_and_architecture.md` (refined by the "Merry Go" brief). Written 2026-07-10. Grounded in a full read of the real code (plan.py, fence.py, validate.py, render.py, models.py, routes/mix.py)._

**STATUS: Slice 1 BUILT + tested (341 backend green). Slices 2a–2d planned, not built.** Per the brief, `ENGINE_VERSION` bumped straight to `m6.0` in Slice 1 and `chain_config_hash` landed in Slice 1 (both moved up from where this doc first placed them). The honest A/B baseline is **m6.0 + rules + chain off** — byte-identical to the loved reference (proven by the Slice-2b golden-file test, once built). Verifications below are confirmed against this machine's ffmpeg.

## The goal, in one breath

Turn the mixer from a **placement** engine (lay a clean vocal on the beat) into a **production** engine (actually process the vocal so it sits in the mix like a real remix), stop shipping the AI arrangement the founder dislikes, and turn `fence.py` from a bouncer (declines clashing keys) into a repairman (pitch-nudges them to fit) — **writing every processing decision onto the timeline as an instruction** (the G5 principle), so v2's live engine is a new player for the same sheet music.

Everything ships **off by default**; each of the nine vocal stages has its own kill switch; disabled == byte-identical to today's render.

## Day-1 decisive check (T4) — RESOLVED

`ffmpeg -h filter=rubberband` → **the `rubberband` filter is present AND exposes `formant`** — but its default is `shifted` (the CHIPMUNK mode); `preserved` must be passed explicitly. `pitchq` defaults to `quality` (good). `librosa` is **not** installed and can't be (ARM machine — known constraint).

**Decision (locked):** pitch shift uses `rubberband=pitch=<2^(semitones/12)>:formant=preserved:pitchq=quality`, cap **±3 semitones**. Never rely on the `formant` default. No librosa branch, no new dependency. Even with formants preserved, ±3 st is _audible_ — "much reduced risk," not "no risk."

`ffmpeg -filters | grep -Ei "reverb|afir|aecho"` → **no native reverb.** Only `aecho` (an echo, not a reverb) and `afir` (convolution — needs an IR file). **Decision:** stage 8 = a small **deterministic numpy-convolution reverb** with a short synthetic IR (golden-file-friendly, no binary asset in git); `afir`+bundled IR is the higher-quality alternative. Do NOT pass an echo off as reverb.

## The load-bearing principle (why we don't shortcut)

The renderer decides nothing. Every processing choice is a written instruction on the timeline — we extend the existing, correct `StemMove` pattern to a new domain (`VocalProcessMove`, `DuckMove`). We do NOT reach into `render.py` and apply `tanh` inline; that would be invisible to the future live "more grit" command. The plan carries `{start_bar, saturate_wet, ...}`; the engine obeys.

## Dangerous-surface map (what needs the heavy path)

| File                                      | In dangerous list?                                                                                          | Touched in            |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------- |
| `plan.py`                                 | No                                                                                                          | Slice 1, 2a           |
| `models.py`                               | No                                                                                                          | Slice 1, 2a           |
| `fence.py`                                | No                                                                                                          | Slice 1, 2a, 2d       |
| `routes/mix.py`                           | No                                                                                                          | Slice 1, 2b (version) |
| `workers/render.py`                       | **YES**                                                                                                     | **Slice 2b**          |
| `planner/validate.py`                     | **YES**                                                                                                     | **Slice 2c**          |
| `.github/workflows/**` + golden-file test | **YES**                                                                                                     | **Slice 2b (CI)**     |
| `config.py`                               | **YES** — so we AVOID it: `VocalChainConfig` lives in `models.py`/a new `planner/chain.py`, NOT `config.py` | —                     |

## The slices (each independently shippable; safe → dangerous)

### Slice 1 — Ship the safe win (LIGHT, no dangerous surface) ✅ do first

Resolves the standing #1 product problem immediately; the founder can judge by ear the same day.

✅ **DONE (2026-07-10, 341 backend green).**

1. ✅ **T1 — default to the loved rules arrangement.** In `plan.py`, `USE_AI_ARRANGEMENT = False` (env-overridable); the `_ai_arrange(...)` call is gated behind it → `_ai_arrange` never runs → every mix is the rules path. One-line flip back on. `source` tracks "ai"/"rules".
2. ✅ **T1.2 — attach + log `camelot_fit`.** `models.CamelotFit` (both camelot codes + `compatible`, `None` on unknown key); `fence.camelot_detail` reuses `camelot_fit()`; attached as `MixPlan.camelot_fit`; logged in `_run_mix`. Informational — **never gates**. (Shortest-shift computation deferred to `compute_pitch_repair` in 2a — kept Slice 1 truly read-only.)
3. ✅ **T1.3 — cache refresh.** `ENGINE_VERSION m5o.0 → m6.0` in `routes/mix.py` (per the brief — this is the A/B baseline, not a smaller bump). **Zero cloud cost** — stems/analysis keyed by song_id, never read the version (grep-confirmed).
4. ✅ **T1.4 — `chain_config_hash` into the cache id.** `models.VocalChainConfig` (defined now, `enabled=False`) + `models.chain_config_hash`; `_CHAIN_CONFIG_HASH = chain_config_hash(VocalChainConfig())` folded into `mix_id_for`, so tuning-week dial changes invalidate cleanly. Defining the real config now (vs a placeholder) keeps the hash stable from the start — avoids a second invalidation later.

- **Acceptance (met):** every fresh mix reports `source: "rules"` + `_ai_arrange` never called; `MixPlan.camelot_fit` present + logged; `mix_id` folds the chain hash; suite green; the render is unchanged for a given plan.
- **Risk:** low. Reversible (flip the flag). No dangerous file.

### Slice 2a — Declarative scaffolding (LIGHT, no dangerous surface, zero behavior change)

Lay the timeline instructions and config, all OFF, so nothing changes yet.

1. **`models.py` (additive):** `VocalProcessMove` (placement_id, start_bar, end_bar, per-stage dials, `reason`), `DuckMove` (target_stems, key_placement_id, depth_db, attack/release). Add to `MixPlan`: `vocal_moves: list[VocalProcessMove] = []`, `duck_moves: list[DuckMove] = []`. All additive → old plans parse. _(`VocalChainConfig` + `chain_config_hash` already landed in Slice 1 for the cache key.)_
2. **`plan.py`:** when `chain_config.enabled` (default False) → emit `VocalProcessMove`/`DuckMove` per placement; when off → emit none (so `MixPlan.vocal_moves == []`, exactly like `stem_moves == []` today).
3. **`fence.py`:** `compute_pitch_repair(a1, a2, cfg) -> shift | Decline` — **arithmetic only**, shortest legal semitone shift into key compatibility, decline > ±3. Includes the load-bearing docstring: _this is arithmetic, not taste; choosing among legal shifts is Phase 3._ Computed here, not yet applied.

- **Acceptance:** with chain disabled, `MixPlan.vocal_moves == []` and the render is byte-identical to Slice 1; models round-trip; `compute_pitch_repair` unit-tested. **No dangerous file touched.**

### Slice 2b — The nine-stage render chain (HEAVY — `render.py` + CI golden-file)

The production engine. Reads `VocalProcessMove`s; obeys, never decides.

- **Signal flow (two engine boundaries, not nine):**
  - Stages **1 de-ess, 2 high-pass, 5 compress, 7 presence EQ, 8 reverb** → **one FFmpeg filtergraph** (single decode/encode) applied to the vocal slice.
  - Stage **3 pitch** → ffmpeg `rubberband` (separate pass). Stage **4 time-stretch** → existing `atempo`/warp code, untouched. Stage **6 saturate** → numpy `tanh` soft-clip (3 lines; `wet` hard-capped 0.5).
  - Order rule **🔴 stage 1 (de-ess) MUST precede stage 6 (saturate)** — enforced structurally by a fixed-order pipeline, not a user list.
  - Stage **9 duck** → **bed-side**, keyed by the placed vocal. Reuses the existing per-sample gain-envelope machinery (`_stem_envelope`) — a `DuckMove` becomes bed-stem gain reduction over the vocal's span. Runs at mix time, after placement.
- **The invariant:** `chain_config.enabled == False` (→ no `vocal_moves`) ⇒ **byte-identical to `m5o.1`**. Mirrors the existing "no StemMoves ⇒ byte-identical bed" invariant — holds by construction (empty list → unchanged path).
- **CI golden-file test:** disabled render hashes to the `m5o.1` reference; build fails otherwise. Pin ffmpeg version for determinism (G2).
- **Ceremony:** independent **test-author** subagent writes failing tests vs approved acceptance; **adversarial-safety quorum** (correctness / DSP-distortion / blast-radius / reproduces) must ALL return safe; then **confirm-and-apply** (founder yes → `.zuko/approve.js` → apply).

### Slice 2c — The referee rules P1–P5 (HEAVY — `validate.py`)

The quality guardrail gains five rules; it re-derives independently, never trusts the plan.

| Rule   | Check                                                                                                                                                                                                                                                                       |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P1** | `VocalProcessMove.pitch_semitones` within ±3 (±2 if ever on librosa — n/a here)                                                                                                                                                                                             |
| **P2** | Pre-master peak ceiling: no stage's output peak > −3 dBFS before the master. (Render-side guard exposes the pre-normalize bus peak; referee asserts it. Pragmatic detail resolved in the 2c brainstorm — P3's hard caps bound it deterministically as the belt-and-braces.) |
| **P3** | Chain param bounds: `saturate_wet ≤ 0.5`, `presence_gain_db ≤ 6.0`, every dial in its declared range                                                                                                                                                                        |
| **P4** | Duck sanity: only ducks (never boosts), depth ≤ 6 dB, never targets the vocal stem — mirrors the existing StemMove "no boosts" rule                                                                                                                                         |
| **P5** | Timeline anchoring: every move's bar range lands on downbeats and overlaps exactly one placement                                                                                                                                                                            |

- **Ceremony:** full heavy path as 2b (test-author + adversarial quorum + confirm-and-apply).

### Slice 2d — Repair-instead-of-decline, wired (LIGHT-ish — `fence.py`/`plan.py`)

Turn `compute_pitch_repair` from computed to applied: when a pair clashes in key but is fixable within ±3, emit a pitch `VocalProcessMove` and **accept** instead of declining. Still gated by `chain_config.enabled`. Catalog-expansion note: compatibility is pairwise, so pitch-flexing one song adds a _row_ of new legal mixes, not one.

### Flip day (founder-gated, after tuning week)

`chain_config.enabled = true`; `ENGINE_VERSION → m6.0`; fold `chain_config_hash` into `mix_id_for` so tuning-week dial changes auto-invalidate without a manual bump. Mix cache invalidates once (CPU-only). **Zero Replicate calls.**

## Tuning week (founder ear-time — not optional, not in the build days)

Render 10 reference pairs (incl. the loved reference) under `m5o.1` vs `m6.0`; blind A/B; move ONE dial at a time; when something sounds wrong, **bisect by disabling stages**, never guess. Suggested order (most→least perceptible): `saturate_wet → presence_gain_db → reverb_wet → duck_depth_db → compress_ratio → highpass_hz → deess_intensity`. **Do this in the `C:\DJ-AI-Experiment` sandbox first, ear-confirm, then the dials port to main** (founder's standing workflow). The winning numbers become `bollywood_vocal_over_house` v1 (the Phase-3 recipe seed).

## Risk register (PRD §10 + build notes)

- **Ugly pre-master distortion** → P2 + P3 hard caps; `saturate_wet ≤ 0.5`.
- **Chipmunk pitch** → resolved: rubberband present, formants preserved, ±3 cap.
- **Nine passes degrade audio** → one filtergraph (2 encodes total), enforced in review.
- **Determinism drift** → pin ffmpeg; golden-file CI gate.
- **Duck wired as a vocal op** → called out: duck is bed-side, keyed by the placed vocal.
- **Config on a dangerous surface** → `VocalChainConfig` deliberately NOT in `config.py`.

## Acceptance (PRD §8), mapped to slices

- `_ai_arrange` no longer activates on key presence → **1**
- `camelot_fit` on every plan, logged, not gated → **1**
- Nine stages, fixed order, each disable-able → **2b**
- Pitch band by referee (P1), >±3 declines → **2c/2d**
- Pre-master ceiling (P2) → **2c**
- All vocal processing as timeline instructions (G5) → **2a/2b**
- Determinism, identical bytes 10/10 → **2b golden-file**
- Zero Replicate calls from the bump → all (content-addressed)
- Founder A/B new render wins ≥8/10 → **tuning week**
