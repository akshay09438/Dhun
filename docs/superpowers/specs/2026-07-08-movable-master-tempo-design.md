# Movable-master tempo — meet slow×fast pairs at a shared tempo (design)

_Approved in conversation on 2026-07-08. Built on `feat/house-bollywood-energy-sync`, before Step 3. Unblocks pairs the app declines purely on tempo — the founder's #1 favourite, Father Ocean × Tere Bina — by meeting the two songs at a shared tempo between them (a real DJ's deck-tempo move), stretching **both** songs a little instead of yanking one song 15%._

## The user job (why)

Today the app makes Song 1 (Father Ocean, 122 BPM) the immovable master and stretches only Song 2's vocal onto it. For a slow/fast gap like Tere Bina (~144 BPM), that's a one-sided ~15% stretch — outside the safe band — so the app **declines** the pair. Tere Bina is the founder's emotional proof pair; "it won't even build" is the single biggest gap between the app and the reference mashups (recipe §1.5). A DJ meets two tracks at a shared deck tempo _between_ them so neither warbles much. This makes those emotional slow-burn pairs playable. Honest limit: a big-gap pair still warbles a little (a real stretch) — just far less than one-sided.

## The policy (founder's call, 2026-07-08): only when needed

The movable master engages **only** when the current one-sided lock would fall outside the safe band. When a pair already fits (every current catalog pair does), Song 1 stays at its native tempo exactly as today. So this change is **purely additive**: it rescues previously-declined pairs and changes nothing — not one sample — about pairs that already worked. Every existing mix renders identically.

## The one architectural principle (unchanged)

The brain plans a `MixPlan` (JSON); the deterministic engine executes; the LLM never touches audio. This step adds one additive plan field (`bed_stretch`) and one engine step (stretch Song 1's stems), all gated so `bed_stretch == 1.0` is byte-for-byte today.

## The math (`app/planner/fence.py`, safe surface)

1. Fold `bpm2` to the octave (×0.5 / ×1 / ×2) nearest `bpm1` → `bpm2'` (reusing `best_stretch`'s octave logic — a ~72 ballad read as 144 folds the same either way).
2. **One-sided first (only-when-needed):** if `best_stretch(bpm1, bpm2)` is already in the safe band → **native master**: `master_bpm = bpm1`, `bed_stretch = 1.0`, `vocal_stretch =` the one-sided ratio. Today's path, untouched.
3. **Otherwise meet in the middle:** target `T = sqrt(bpm1 · bpm2')` (the geometric mean — it makes the two stretches symmetric around 1.0, i.e. minimises the worse one). `ratio1 = T/bpm1` (the bed), `ratio2 = T/bpm2'` (the vocal). If **both** are within `[SAFE_STRETCH_LO, SAFE_STRETCH_HI]` → mixable at `T`: `master_bpm = T`, `bed_stretch = ratio1`, `vocal_stretch = ratio2`. Else **decline** (genuinely too far apart even meeting in the middle). This widens the mixable set from a one-sided ±11% to a two-sided gap of ~±23% — enough to reach Tere Bina (144 vs 122 → T≈132.5, each ~±9%, in band).

`SAFE_STRETCH_LO/HI` are **unchanged** — we choose a smarter target so both stretches already fit the existing tight band, never loosen the band.

## Retime Song 1's analysis (`fence` / `plan`, safe surface)

When `bed_stretch ≠ 1.0`, build a **retimed copy** of Song 1's `TrackAnalysis`: every time field (`beats`, `downbeats`, `phrase_starts`, each `section.start/end`, each `vocal_regions` span) multiplied by `1/bed_stretch` (= `bpm1/T`), and `bpm = T`. `energy_curve` values are per-bar and unchanged (only re-timestamped via the scaled downbeats). The **existing planner runs on this retimed analysis** — so anchors, drops, warp maps, placements and Song-1 lead regions all come out in the stretched timeline with no other planner change. Pure arithmetic; no new imports.

## The engine (`workers/render.py`, **dangerous surface**) — pre-stretch Song 1's stems

The whole change is one gated step at the top of `render_mix`: when `bed_stretch ≠ 1.0`, `atempo`-stretch each Song-1 stem (drums, bass, other, and Song 1's vocals) by `bed_stretch` into temp files, and run the **existing render logic verbatim** on those stretched stems. After stretching, the stems sit at tempo `T` on the retimed grid — exactly the timeline the plan's anchors, warp and `s1_vocal_regions` are already expressed in — so every downstream slice, warp and placement is unchanged. `bar` already derives from `plan.master_bpm` (= `T`). Reuses the existing `atempo` path (a small `ratio` on the decode step); no duplicated DSP, no new imports. `bed_stretch == 1.0` skips the step entirely → identical to today.

## The referee (`app/planner/validate.py`, **dangerous surface**) — additive checks

The referee still runs against the **original** `a1` (native grid), so it rescales to the plan's timeline using the plan's own `bed_stretch` — a single source of truth the engine and referee share (the `placement_end` pattern):

- **B3 (safe stretch):** `vocal_stretch` in band (unchanged) **and** `bed_stretch` in band (new — the bed's stretch must be safe too).
- **R3 (on-beat) / R7 (warp locks to grid):** compare against `a1`'s downbeats **rescaled by `1/bed_stretch`** (= `1.0`, a no-op, for every existing plan). So an entry/boundary is "on the beat" relative to the stretched grid the audio actually plays at.
- **R1 (one vocal), R6 (no clip / not silent):** unchanged; R6 on the real audio is the ultimate backstop regardless of tempo.

## Data model (`app/models.py` — additive) & route

- `MixPlan.bed_stretch: float = 1.0` — the ratio Song 1's bed is stretched by. `1.0` = native master (today). Old cached plans default to `1.0` and render unchanged.
- `routes/mix.py`: bump `ENGINE_VERSION` so no stale native-tempo mix is served for a pair now mixed at a shared tempo. No new inputs (the engine already receives all four Song-1 stems).

## Invariants (the iron rules, and how each is held)

1. **One bassline** — still only Song 1's bass, now time-stretched; never two. ✅
2. **One lead vocal** — vocal rules untouched; both stretches keep the same single-vocal construction. ✅
3. **Every move on the beat** — the plan is built and validated on the retimed grid; the stretched audio plays at that grid. ✅
4. **Never clip / never silent** — peak-normalize + clip guard + real-audio R6, unchanged. ✅
5. **Old mixes still work** — `bed_stretch` defaults `1.0`; only-when-needed means every currently-mixable pair keeps `bed_stretch == 1.0` and renders identically. ✅

## Acceptance (how we'll know it worked)

- **Machinery proof (free, cached):** force meet-in-the-middle on a pair we already have (Father Ocean × Tujhe Bhula Diya at a shared tempo instead of the vocal-only stretch) — the founder hears that stretching Father Ocean's bed still sounds clean and the mix stays on-beat and click-free.
- **The real payoff:** once the founder provides Tere Bina's audio and it's ingested (split + analyzed), Father Ocean × Tere Bina **produces a mix at all** (previously declined) at ~133 BPM, both stretches ~±9%, on-beat, no clip — with the full approved recipe (energy-sync, both vocals trade, hand-off, echoes) riding on top. The founder listens for warble (a little expected) and we tune.
- A previously in-band pair is checked to render **identically** (bed_stretch stays 1.0).

## Dangerous surfaces (heavy path)

`workers/render.py` + `services/api/app/planner/validate.py` — additive, pre-launch. Route: an independent test-author writes the failing tests first; a fresh adversarial-safety panel tries to prove it unsafe (could the bed and vocal drift apart? an off-band bed stretch slip through? a retime error push entries off-beat? an old mix change?); the founder gets a plain-language explanation and gives an explicit **yes**; applied via confirm-and-apply (`.zuko/approve.js`); the founder listens. (The pre-existing R1 relaxation's fresh adversarial pass before merge is still separately owed.)

## Tests (same PR; dangerous-file tests authored independently)

- `test_models` — `bed_stretch` additive; defaults `1.0`; an old plan JSON without it still parses.
- `test_fence` — in-band pair → native master (`bed_stretch == 1.0`); a slow/fast pair (122 × 144) → shared target `T`, both stretches in band; a truly-far pair still declines; octave-folded (72) reads the same as 144.
- `test_plan` — retimed analysis scales the grid by `1/bed_stretch`; anchors/warp land on the retimed grid; an in-band pair is unchanged.
- `test_validate` — an off-band `bed_stretch` is flagged (B3); R3/R7 pass on the retimed grid and still catch a genuinely off-beat entry; an old plan (`bed_stretch == 1.0`) validates exactly as before.
- `test_render` — a `bed_stretch ≠ 1.0` plan stretches the bed to the target length, stays on-beat, no clip, not silent; **a `bed_stretch == 1.0` plan renders identically to the pre-change engine** (the old-mixes-still-work proof).
- `test_mix_route` — `ENGINE_VERSION` bumped.

## Out of scope (later)

Live/real-time tempo change (V2) · pitch-shift for key clashes (V2 — e.g. Suniyan Suniyan's key, a separate problem from tempo) · Step 3 stem dynamics (the next build, after this) · "always meet in the middle" for cleaner close-pairs (deferred by the only-when-needed decision; revisitable).
