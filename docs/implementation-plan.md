# Prompt-DJ — Implementation Plan

*How far along we are, what's in flight, what's left, and the drift log. Living document — updated at each milestone and at `/zuko:handoff`.*

## Status: **Setup complete. No app code yet.** Next: M1.

Demand is founder-validated, so we skipped the hand-made validation gate (former "M0"); the first real proof point is **M2/M3** — the first genuinely good mix.

## Milestones

| # | Milestone | Goal | Acceptance | Status |
|---|---|---|---|---|
| M1 | Skeleton | Two-file upload → normalized WAV, stored; app runs end to end | Upload two songs, get them back re-encoded | ☐ Not started |
| M2 | Analysis + stems | `TrackAnalysis` (with per-field confidence) + `StemSet`, cached; overlays in UI | BPM ±1 and downbeats on the one for demo pairs; isolated vocal intelligible | ☐ |
| M3 | Basic mix | Song 1 bed + Song 2 vocal placed on the drop, tempo-locked, phrase-aligned; export WAV | Drift-free, on-phrase, click-free, single vocal — **the first "whoa"** | ☐ |
| M4 | Full DJ arrangement | Judgment layer: varied placement, beat-drop breaths, keep-S1-vocal, ≥2 placements, FX, confidence fallbacks, **regenerate** | Success criteria S1–S4 on demo set; regenerate yields a different valid plan | ☐ |
| M5 | Lean live control | Stem-bus player + on-beat scheduling; the lean command set; orchestration; out-of-scope decline | Every command lands on the beat, no artifact/stall | ☐ |
| M6 | Polish + share | Loudness/limiter; short-clip export; the ~50-user test | Clean master; ~50 creators feel the magic | ☐ |

## Deltas from the original PRD (decided during discovery, 2026-07-05)
- One target user (casual creators), not three.
- Feature 2 leaner + Regenerate promoted to first-class.
- Short-clip (15–30s) export added as a hero output.
- Live BPM change explicitly deferred to V2.
- Right-sized stack: SQLite + local storage + in-process jobs for validation (audio toolchain unchanged).
- Time-stretch: SoundTouch (free) by choice, swappable to Rubber Band.

## Curated demo pairs (to assemble before/with M3)
~10 pairs: mostly *compatible* (close BPM, Camelot-adjacent, clear structure) to showcase quality; 2–3 *hard* pairs to exercise fallbacks. Hand-verify grid/key/sections. Include a couple of Indian pairs, hand-checked (weaker analysis there).

## Drift log
*(record any place the docs and code diverge, and how it was resolved)*
- 2026-07-05 — Repo bootstrapped from discovery. No code yet; specs are intended design, not as-built.
