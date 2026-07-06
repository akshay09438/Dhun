# M4 Slice A — The Living Arrangement + Regenerate (design)

_Approved in conversation on 2026-07-06. Turn M3's single vocal drop into a full DJ arrangement (the vocal weaving in and out across several sections, energy shaped like a set, a real beat-breath) plus a "give me another take" (Regenerate) button and a mix screen that shows the arrangement. Slice B (keep-Song-1-vocal, FX, richer confidence fallbacks) is deferred to a clean follow-up._

## The user job (why)

M3 proved two songs lock cleanly, but a single vocal over minutes of untouched instrumental isn't something a casual creator would post. Slice A delivers the product's core success bar — "I made a real mix I'd actually share" — by making the mix feel _arranged_, and Regenerate lets the user get a different valid take instantly (a headline V1 feature).

## The one architectural principle (unchanged)

The brain plans a structured `MixPlan`; the deterministic engine executes it; the LLM never touches audio. Slice A grows the _plan_ from one placement to a full arrangement, and grows the AI's role from "pick the drop" to "arrange the set" — still only ever choosing among options the rules (fence) declare legal, still checked by the referee.

## Data model — extend `MixPlan` additively (do not break M3's cached JSON)

Add an optional `placements: list[Placement]` to `MixPlan`; keep the M3 scalar `anchor` / `vocal_src` as the single-placement fallback so **old cached plan JSON still parses** (the scalability reviewer's one-way-door note). New models:

- `Placement` — one vocal moment: `anchor` (secs into Song 1, a downbeat), `vocal_src` ([start,end] of Song 2's vocal), `beat_breath` (bool — a one-bar tension dip right before this entry).
- `MixPlan.placements: list[Placement]` (optional). The engine prefers `placements` when present; if absent it renders the single `anchor`/`vocal_src` (M3 behaviour).
- `MixPlan.take: int` (which regenerate iteration; 1-based) so takes are distinct and cacheable.

## The fence (extended, deterministic)

Beyond M3's legal-options, the fence now offers an **arrangement menu**: the ranked candidate drop phrases (already have), plus each candidate's Song-1 section label and energy (for stage-matching + arc), and the set of Song-2 vocal slices available (its chorus/strong regions). It still declines unmixable pairs and folds octaves for tempo. New helper: `arrangement_options(a1, a2)` returning `{sections_with_energy, vocal_slices, ...}` on top of the M3 legal set.

## The AI driver (arranges the set)

Claude now plans a **full arrangement**: pick 2–4 placements mapping Song-2 vocal slices onto Song-1 sections, following an energy arc (quiet intro instrumental → vocal on a chorus → out for a verse → back for the finish), preferring chorus-over-chorus (Handbook A2), never starting the vocal in the first phrase, and marking a `beat_breath` before a big re-entry. Constraints handed to the model: ≥2 placements, no two vocal takes overlapping in time (one voice at a time), entries on downbeats. **Deterministic fallback** (no network / low confidence): take the top-N energy phrases as anchors, map the strongest vocal slices to them spaced out — a valid, simple arrangement. **Regenerate** = re-plan with variation: the AI call varies (temperature / "give me a different arrangement than take N") and the fallback rotates through candidate combinations; each take yields a genuinely different valid plan.

## The referee (`planner/validate.py`, dangerous surface) — new hard rule R5

- **R5 (≥2 distinct vocal placements)** for a full arrangement (a single placement is the M3 shape, allowed only as the low-confidence fallback).
- **R1 (one vocal at a time)** now means _placements must not overlap_ — sort by anchor, assert each vocal take ends before the next begins; still guaranteed single-source (only Song 2's vocal).
- **R3** each placement's anchor is on a Song-1 downbeat; **R6** finished audio is not silent/near-silent and does not clip (M3 guards kept).
- `validate_plan` / `validate_render` extended; a plan failing R5/overlap falls back to a safe simpler arrangement rather than shipping.

## The engine (`workers/render.py`, dangerous surface) — multi-placement + real breath

Loop over `placements`: for each, slice + `atempo`-stretch Song-2's vocal, edge-fade, and sum onto Song-1's continuous bed at the anchor. **Beat-breath done right:** when `beat_breath` is set, _duck_ the bed to ~35% for one bar before the entry (a tension dip) — never silence (the M3 dead-air bug stays fixed). Bass/gain handling and the −1 dBFS peak-normalize + clip guard carry over. Still decoupled (plain file paths, no app/db coupling); the 12-min decode cap and tempo/anchor guards stay.

## Regenerate + the async route (`routes/mix.py`)

`mix_id` folds in `take` (and `ENGINE_VERSION`) so each take is a distinct cached render; `POST /mix` accepts an optional `take` (default 1) — Regenerate calls it with `take+1`. Same start-then-poll async contract; identical (song1, song2, prompt, take) is a free cache hit.

## The mix screen (`apps/web`) — show the arrangement

A two-lane **arrangement timeline**: the "beat" lane (Song 1, plays throughout) and the "vocal" lane (Song 2, blocks where the vocal is in, with a beat-breath marker before big entries), section labels, a legend, and the plain-English DJ note. **Regenerate ("give me another take")** and **Download** buttons, plus a "take N" label. States: mixing (progress), ready (player + timeline + buttons), error/decline (plain reason), first-run (before the first mix). Reuses the app's existing dark/purple visual language.

## Confidence fallback (basic in Slice A)

If Song-1 section/analysis confidence is low, the driver plans **fewer, safer placements** (down to the M3 single drop) rather than a risky busy arrangement — honest degradation (Handbook Part 9). Richer per-element fallbacks are Slice B.

## Dangerous surfaces (same careful path as M3)

`workers/render.py` and `services/api/app/planner/validate.py` are re-touched. Both changes are additive on a pre-launch app → expected risk route low, but handled via the confirm-and-apply flow with the founder's explicit yes, an independent test-author, and an adversarial-safety review before merge.

## Acceptance (how we'll know it worked)

On a compatible pair: the exported mix has the vocal entering and leaving in ≥2 places with the beat continuous underneath, energy that rises and falls (not flat), a tension dip (not silence) before a big entry, only ever one voice, no clipping — and it sounds like a deliberate DJ arrangement, not a single drop. Regenerate produces a clearly different valid arrangement. The mix screen shows the weave and the take number.

## Tests (same PR)

`test_fence` (arrangement options, section/energy mapping, still-declines), `test_plan` (multi-placement plan, regenerate yields a different valid plan, no-overlap, no network), `test_validate` (R5 ≥2, overlap rejected, each entry on a downbeat), `test_render` (multi-placement render, breath ducks not silences, valid/no-clip), `test_mix_route` (take/regenerate + caching), web (arrangement timeline renders in/out + Regenerate). Dangerous-file tests authored independently.

## Explicitly out of scope (Slice B / later)

Keep-Song-1-vocal for contrast · FX (filter sweeps, echo) · richer per-element confidence fallbacks · live commands (M5) · final mastering loudnorm/limiter + short-clip export (M6).
