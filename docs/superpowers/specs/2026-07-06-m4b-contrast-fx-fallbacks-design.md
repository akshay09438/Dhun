# M4 Slice B — Contrast + Subtle FX + Confidence Fallbacks (design)

_Approved in conversation on 2026-07-06. The flourishes that make the arrangement feel like a real mashup: (1) keep Song 1's own vocal for a contrast moment, (2) one subtle filter-sweep into a big entry, (3) the arranger plays safer when a song's analysis is shaky. Additive on top of the working M4 Slice A arrangement._

## The user job (why)

Slice A delivered the living arrangement + regenerate (live-confirmed). Slice B pushes toward "a mix I'd actually post": the two songs **trade vocals** (the defining feel of a mashup, not just one song's vocal over another's beat), a single tasteful build-up, and honest degradation so real/messy uploads don't embarrass the app before the ~50-user test. Effects are deliberately **subtle-only** (DJ Handbook G1: "less is more").

## The one architectural principle (unchanged)

The brain plans a `MixPlan`; the deterministic engine executes; the LLM never touches audio. Slice B adds two additive plan dimensions and the engine moves to realise them — the referee still guarantees the hard rules.

## Data model (additive — M3/M4a cached plans still parse)

- `MixPlan.s1_vocal_regions: list[tuple[float, float]] = []` — spans (secs into Song 1) where **Song 1's own vocal** plays in the mix (the contrast moments). A new list parallel to `placements`; it does **not** overload `Placement.vocal_src` (which is always Song 2's vocal).
- `Placement.fx: str | None = None` — an optional effect on a placement's entry. Slice B supports `"sweep_in"` (a rising low-pass filter sweep over the bar before the entry). `None` = no effect (the default, back-compat).

## The referee (`planner/validate.py`, dangerous) — R1 now spans both voices

The core new guarantee: **Song 1's vocal never overlaps Song 2's vocal** (never two lead voices). `validate_plan` checks every `s1_vocal_regions` span against every Song-2 placement window (`[anchor, placement_end]`, via the shared `fence.placement_end`) and flags any overlap (R1). S1 regions must also be non-empty and within the track. Everything from Slice A (no S2-S2 overlap, on-beat, safe stretch, R6) stays.

## The driver (`planner/plan.py`) — pick contrast, one FX, and gate on confidence

- **Contrast:** after choosing the Song-2 placements, find a **beat-only gap** between them long enough for a contrast moment, and where **Song 1 actually sings** (its analysed `vocal_regions` intersect the gap). Add **one** `s1_vocal_regions` span there (with margin from the neighbouring S2 vocals so they never touch). Tasteful default: a single contrast moment.
- **One subtle FX:** mark the single biggest re-entry placement with `fx="sweep_in"`.
- **Confidence gating (Handbook Part 9):** if Song 1's grid/structure is shaky (`bpm_confidence` or a low structure signal below a threshold), the arranger **plays safe** — fewer placements, and it drops contrast, FX, and beat-breath (never bet fancy moves on bad data). The AI is instructed the same; the deterministic path enforces it.
- Slice A's `_ai_arrange`/fallback and `_dedupe_nonoverlapping` are unchanged for Song-2 placements; contrast + FX + gating layer on after.

## The engine (`workers/render.py`, dangerous) — mix Song 1's voice + the sweep

- **Contrast:** for each `s1_vocal_regions` span, decode **Song 1's vocal stem** (`song1_stems["vocals"]`, already split, normally discarded), slice that span, edge-fade, and add it to the bed at that time. No stretch — Song 1's vocal is already at the master tempo (it _is_ Song 1). The bed itself stays drums+bass+other (Song 1's vocal is only added in these contrast spans).
- **FX `sweep_in`:** for a placement flagged `sweep_in`, apply a **rising low-pass** to the bed over the one bar before the entry — cutoff ramps from muffled (~300 Hz) to open across the bar, done in sub-blocks with `scipy.signal.butter`/`sosfilt`. Bed-only; the −1 dBFS normalize + clip guard still bound the output.
- Still decoupled (plain file paths); the 12-min decode cap and guards stay.

## Route + web

`routes/mix.py` passes Song 1's `vocals` stem into `song1_stems` and bumps `ENGINE_VERSION` (`m4b.1`). The mix screen's arrangement timeline gains a **Song-1-vocal marker** (a distinct colour from Song 2's) and a small **FX mark**, so the contrast and the sweep are visible.

## Acceptance (how we'll know it worked)

On a compatible pair: the mix has Song 2's vocal weaving in AND a Song-1 vocal answering in a gap (the two songs trade), one subtle filter-sweep into a big entry, and — checked against the finished audio and the plan — **never two lead vocals at once**, on-beat, no clipping. On a deliberately shaky song, the arrangement simplifies (fewer moves, no fancy stuff) instead of risking a mess. The timeline shows both voices distinctly.

## Dangerous surfaces (same path as M4a)

`workers/render.py` + `services/api/app/planner/validate.py` re-touched — additive, pre-launch → confirm-and-apply with the founder's yes + an independent adversarial review before merge.

## Tests (same PR)

`test_models` (s1_vocal_regions/fx additive + old JSON parses), `test_fence` (contrast-window selection), `test_plan` (contrast placed only in gaps where S1 sings; FX on one entry; confidence gating simplifies), `test_validate` (S1-vs-S2 vocal overlap flagged), `test_render` (S1 vocal mixed into the span; sweep raises pre-entry brightness; still no clip), `test_mix_route` (S1 vocals passed + version), web (S1-vocal marker renders). Dangerous-file tests authored independently.

## Out of scope (later)

More FX types / multiple FX per mix · continuous keep-both-vocals throughout (V2 territory) · live commands (M5) · mastering + short-clip export (M6) · the mix-cache eviction sweep (top backlog item, before the ~50-user test).
