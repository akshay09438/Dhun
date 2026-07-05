# M3 — The Basic Mix (design)

_Approved in conversation on 2026-07-05. The first real mix: Song 1's instrumental bed + Song 2's vocal, tempo-locked, placed once on the strongest section, on the beat, click-free, exported as WAV. This is the product's first "whoa" and the first implementation of the DJ Judgment Handbook._

## The user job (why)

A casual creator uploads two songs and wants a mix that sounds like a real DJ made it — not two songs pasted on top of each other. M3 proves the **engine**: the two songs lock to one beat and one clean vocal drop lands on the drop, intentionally. The full weaving arrangement (vocal in/out, beat breaths, ≥2 placements, regenerate) is M4.

## The one architectural principle (unchanged)

The **brain plans (a structured `MixPlan`), the engine executes (deterministic DSP)**. The LLM never touches audio samples. It only fills the plan by choosing among options the rules already declared legal.

## The team: fence + AI driver + referee (decided with the founder)

Rules and AI work **together** from M3, not rules-only:

- **The fence** (`planner/fence.py`, deterministic) reads both songs' `TrackAnalysis` and computes the _legal, safe_ options: candidate drop points (phrase-aligned, high-energy), whether the tempo gap is small enough to stretch cleanly, which slice of Song 2's vocal to use, key compatibility (informational in M3).
- **The AI driver** (`planner/plan.py`) — Claude picks the best option + small taste touches (e.g. a one-bar beat breath before the vocal). It only ever chooses from the fence's legal set. On any error/missing key/low confidence it falls back to a deterministic "obvious best" pick, so the app never blocks on the AI. M3's menu is deliberately small; it widens in M4.
- **The referee** (`planner/validate.py`, deterministic) checks the plan **and the finished audio** against the hard rules: R1 single lead vocal at a time, R3 the vocal enters on a downbeat, safe stretch bounds, R6 no clipping / not silent. A failing plan falls back to the safe move; a failing render is rejected.

## Tempo matching

Everything locks to **Song 1's tempo** (the beat is the master clock). Song 2's vocal is time-stretched to Song 1's BPM with **FFmpeg `atempo`** — pitch preserved, so the voice stays in tune. Small stretches only: the safe band is ±8% (`0.92–1.08`). Outside it, the fence declines the pair with a plain-language reason rather than shipping a warbly voice. (Drift from the spec's "SoundTouch": `atempo` is the same class of tool, already installed, needs no extra binary, and is license-clean (LGPL) for a commercial build — GPL `rubberband` is available in this dev FFmpeg but we do **not** depend on it in the pipeline. Logged in the implementation plan.)

## What plays (arrangement, M3)

Song 1's **instrumental** (drums + bass + other stems summed — Song 1's own vocal removed) runs continuously — the music never stops. Song 2's **vocal** enters **once** at the anchor (the drop), sings through its slice, and leaves. Only ever one voice. Optional one-bar beat-breath right before the vocal enters. Single placement by design (M4 adds the full in/out weave and ≥2 placements).

## Data models (`app/models.py`)

- `MixPlan` — the recipe: `mix_id, song1_id, song2_id, master_bpm, vocal_stretch, vocal_src [start,end], anchor (secs, a downbeat of S1), beat_breath, notes (DJ language), confidence, source ("ai"|"rules")`.
- `Mix` — the async job/result: `mix_id, status (processing|ready|error|idle), url?, plan?, message?`.

## The pipeline (stage by stage)

1. **Preconditions** — both songs uploaded, analyzed (`TrackAnalysis` ready), and split (stems ready). If not, the route says what's missing.
2. **Fence** — compute legal options from both analyses. If the tempo gap is unsafe or data is too shaky, decline with a reason.
3. **Driver** — Claude (or the deterministic fallback) picks a `MixPlan` from the legal options.
4. **Validate plan** — referee checks the plan; illegal → safe fallback.
5. **Render** (`workers/render.py`) — build S1 instrumental bed; slice + `atempo`-stretch S2 vocal; place at the anchor with short click-free fades (optional beat-breath); sum; loudness-normalize + limit; write WAV.
6. **Validate render** — referee checks the real audio: not silent, no clipping.
7. **Serve** — cache the WAV by `mix_id`; the web app polls and offers play + download.

## The mix route (`app/routes/mix.py`, async — mirrors stems/analysis)

- `POST /mix` `{song1_id, song2_id, prompt?}` → starts a background job, returns `202 processing` (or the cached result). `mix_id` = content hash of `(song1_id, song2_id, prompt)` so identical requests are cached and free.
- `GET /mix/{mix_id}` → `processing | ready (with plan + url) | error | idle`.
- `GET /mix/{mix_id}/audio` → serves the WAV (id validated before disk access).

## Web (`apps/web`) — minimal for M3

Once both songs are ready, a **Make my mix** action → honest progress screen → a simple mix screen: play the result, a small timeline showing where the vocal enters, and a **Download** button. (Live commands + regenerate are M5/M4; not here.)

## Dangerous surfaces touched (and why safe)

- `workers/render.py` and `app/planner/validate.py` are on the dangerous list (the quality guardrail). Both are **new, additive, pre-launch** → risk scorer route `auto-apply` (low). Guarded by the confirm-and-apply flow; independent test-author + adversarial review before merge.

## How we'll know it worked (acceptance)

On Father Ocean + Tere Bina (a pair with a known real remix): the exported WAV plays start to finish with no clicks/drift, both songs share one beat, only one voice sings at a time, no distortion, and it honestly sounds like a deliberate DJ move — not a flat paste.

## Tests (same PR)

`test_fence` (legal options, stretch bounds, drop ranking, fallbacks), `test_plan` (driver fallback path, no network), `test_validate` (each hard rule), `test_render` (valid WAV, right length, no clipping, single-vocal), `test_mix_route` (async contract, caching, precondition errors), one web test. Dangerous-file tests authored independently.
