# Movable-master tempo — meet slow×fast pairs at a shared tempo (design)

_Approved in conversation on 2026-07-08. Built on `feat/house-bollywood-energy-sync`, before Step 3. Unblocks pairs the app declines purely on tempo — the founder's #1 favourite, Father Ocean × Tere Bina — by nudging the house track to a shared tempo. **House-protective (founder's call, 2026-07-08): the house/EDM track is the anchor and moves the MINIMUM — it may speed up a little but is never dragged down more than a hair; the guest vocal absorbs the rest of the stretch.** Slowing a techno/house track kills its drive, so an even 50/50 split is wrong for this genre._

## The user job (why)

Today the app makes Song 1 (Father Ocean, 122 BPM) the immovable master and stretches only Song 2's vocal onto it. For a slow/fast gap like Tere Bina (~144 BPM on the grid), that's a one-sided ~15% stretch — outside the safe band — so the app **declines** the pair. Tere Bina is the founder's emotional proof pair; "it won't even build" is the single biggest gap between the app and the reference mashups (recipe §1.5). The fix nudges the house track just enough that the vocal's remaining stretch falls back inside the safe band — protecting the house (see below) rather than splitting the difference. This makes those emotional slow-burn pairs playable. Honest trade-off: because the house is protected, the vocal takes the larger stretch and warbles a little (it sits near the edge of the safe band) — the price of keeping the house's drive intact, and tunable by ear.

## The policy (two founder calls, 2026-07-08)

1. **Only when needed.** The movable master engages **only** when the current one-sided lock would fall outside the safe band. When a pair already fits (every current catalog pair does), Song 1 stays at its native tempo exactly as today. So this change is **purely additive**: it rescues previously-declined pairs and changes nothing — not one sample — about pairs that already worked. Every existing mix renders identically.
2. **Protect the house.** When it does engage, the house track moves the **minimum** amount needed to bring the vocal back into the safe band, bounded to a small slow-down and a modest speed-up (`HOUSE_SLOW_MAX`, `HOUSE_SPEED_MAX` — tunable by ear). The **guest vocal absorbs the rest** and sits near the edge of the safe band (more warble on the vocal, none of the house's drive lost). A house track that would have to move beyond its bounds to fit → **declined**.

## The one architectural principle (unchanged)

The brain plans a `MixPlan` (JSON); the deterministic engine executes; the LLM never touches audio. This step adds one additive plan field (`bed_stretch`) and one engine step (stretch Song 1's stems), all gated so `bed_stretch == 1.0` is byte-for-byte today.

## The math (`app/planner/fence.py`, safe surface) — house-protective, minimum move

New constants (tunable by ear): `HOUSE_SLOW_MAX = 0.04` (the house may slow at most 4% — protect its drive) and `HOUSE_SPEED_MAX = 0.08` (it may speed at most 8% — don't rush it). The vocal stays inside the existing `[SAFE_STRETCH_LO, SAFE_STRETCH_HI]` (0.89–1.11) — that band is **unchanged**.

1. Fold `bpm2` to the octave (×0.5 / ×1 / ×2) nearest `bpm1` → `bpm2'` (reusing `best_stretch`'s octave logic — a ~72 ballad read as 144 folds the same either way; on the grid it counts _faster_ than 122).
2. **One-sided first (only-when-needed):** if `best_stretch(bpm1, bpm2)` is already in the safe band → **native master**: `master_bpm = bpm1`, `bed_stretch = 1.0`, `vocal_stretch =` the one-sided ratio. Today's path, untouched.
3. **Otherwise, move the house the MINIMUM to bring the vocal into band.** The vocal is in band iff `T/bpm2' ∈ [LO, HI]`, i.e. `T ∈ [LO·bpm2', HI·bpm2']`. We want `bed_stretch = T/bpm1` as close to `1.0` as possible → pick `T = clamp(bpm1, LO·bpm2', HI·bpm2')` (the value in the vocal-legal range nearest the house's own tempo):
   - guest faster on the grid (Tere Bina, `bpm2' > bpm1`): `T = LO·bpm2'` → the vocal sits at its slow edge and the **house speeds up** the minimum (never slows). E.g. 122 × 144: `T = 0.89·144 = 128.2` → `bed_stretch = 1.05` (house +5%), `vocal_stretch = 0.89`.
   - guest slower (`bpm2' < bpm1`): `T = HI·bpm2'` → the **house slows** the minimum.
4. **House-protection gate:** mixable only if `bed_stretch ∈ [1 − HOUSE_SLOW_MAX, 1 + HOUSE_SPEED_MAX]` (and the vocal is in band by construction). Otherwise **decline** — the house would have to move more than it's allowed. This is what makes Tere Bina play (house +5%, inside +8%) while still refusing a genuinely-incompatible pair.

Minimum-move deliberately parks the vocal at the band edge (max allowed warble) to keep the house move smallest — the founder's "protect the house" call. Dialling `HOUSE_SLOW_MAX`/`HOUSE_SPEED_MAX` up lets the house share more of the stretch and calms the vocal; that's the by-ear knob.

## Retime Song 1's analysis (`fence` / `plan`, safe surface)

When `bed_stretch ≠ 1.0`, build a **retimed copy** of Song 1's `TrackAnalysis`: every time field (`beats`, `downbeats`, `phrase_starts`, each `section.start/end`, each `vocal_regions` span) multiplied by `1/bed_stretch` (= `bpm1/T`), and `bpm = T`. `energy_curve` values are per-bar and unchanged (only re-timestamped via the scaled downbeats). The **existing planner runs on this retimed analysis** — so anchors, drops, warp maps, placements and Song-1 lead regions all come out in the stretched timeline with no other planner change. Pure arithmetic; no new imports.

## The engine (`workers/render.py`, **dangerous surface**) — pre-stretch Song 1's stems

The whole change is one gated step at the top of `render_mix`: when `bed_stretch ≠ 1.0`, `atempo`-stretch each Song-1 stem (drums, bass, other, and Song 1's vocals) by `bed_stretch` into temp files, and run the **existing render logic verbatim** on those stretched stems. After stretching, the stems sit at tempo `T` on the retimed grid — exactly the timeline the plan's anchors, warp and `s1_vocal_regions` are already expressed in — so every downstream slice, warp and placement is unchanged. `bar` already derives from `plan.master_bpm` (= `T`). Reuses the existing `atempo` path (a small `ratio` on the decode step); no duplicated DSP, no new imports. `bed_stretch == 1.0` skips the step entirely → identical to today.

## The referee (`app/planner/validate.py`, **dangerous surface**) — additive checks

The referee still runs against the **original** `a1` (native grid), so it rescales to the plan's timeline using the plan's own `bed_stretch` — a single source of truth the engine and referee share (the `placement_end` pattern):

- **B3 (safe stretch):** `vocal_stretch` in `[SAFE_STRETCH_LO, SAFE_STRETCH_HI]` (unchanged) **and** `bed_stretch` within the house bounds `[1 − HOUSE_SLOW_MAX, 1 + HOUSE_SPEED_MAX]` (new — the house's stretch must be inside its protected range, a _tighter_ bound than the vocal's).
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

- **Machinery proof (free, cached):** force the movable master on a pair we already have (Father Ocean × Tujhe Bhula Diya) so the house is nudged a few % — the founder hears that stretching Father Ocean's bed still sounds clean and the mix stays on-beat and click-free.
- **The real payoff:** once the founder provides Tere Bina's audio and it's ingested (split + analyzed), Father Ocean × Tere Bina **produces a mix at all** (previously declined) — the house nudged **up ~5%** (never slowed) and the vocal brought down to the band edge, on-beat, no clip — with the full approved recipe (energy-sync, both vocals trade, hand-off, echoes) on top. The founder listens for vocal warble (some expected, since the vocal takes the whole stretch) and we tune `HOUSE_SLOW_MAX`/`HOUSE_SPEED_MAX` by ear.
- A previously in-band pair is checked to render **identically** (bed_stretch stays 1.0), and the house is confirmed **never dragged below** `1 − HOUSE_SLOW_MAX`.

## Dangerous surfaces (heavy path)

`workers/render.py` + `services/api/app/planner/validate.py` — additive, pre-launch. Route: an independent test-author writes the failing tests first; a fresh adversarial-safety panel tries to prove it unsafe (could the bed and vocal drift apart? an off-band bed stretch slip through? a retime error push entries off-beat? an old mix change?); the founder gets a plain-language explanation and gives an explicit **yes**; applied via confirm-and-apply (`.zuko/approve.js`); the founder listens. (The pre-existing R1 relaxation's fresh adversarial pass before merge is still separately owed.)

## Tests (same PR; dangerous-file tests authored independently)

- `test_models` — `bed_stretch` additive; defaults `1.0`; an old plan JSON without it still parses.
- `test_fence` — in-band pair → native master (`bed_stretch == 1.0`); a slow/fast pair (122 × 144) → **house moves the minimum and only UP** (`1.0 < bed_stretch ≤ 1 + HOUSE_SPEED_MAX`), vocal lands in band at its edge; a pair that would need the house to slow past `HOUSE_SLOW_MAX` still declines; octave-folded (72) reads the same as 144.
- `test_plan` — retimed analysis scales the grid by `1/bed_stretch`; anchors/warp land on the retimed grid; an in-band pair is unchanged.
- `test_validate` — an off-band `bed_stretch` is flagged (B3); R3/R7 pass on the retimed grid and still catch a genuinely off-beat entry; an old plan (`bed_stretch == 1.0`) validates exactly as before.
- `test_render` — a `bed_stretch ≠ 1.0` plan stretches the bed to the target length, stays on-beat, no clip, not silent; **a `bed_stretch == 1.0` plan renders identically to the pre-change engine** (the old-mixes-still-work proof).
- `test_mix_route` — `ENGINE_VERSION` bumped.

## Out of scope (later)

Live/real-time tempo change (V2) · pitch-shift for key clashes (V2 — e.g. Suniyan Suniyan's key, a separate problem from tempo) · Step 3 stem dynamics (the next build, after this) · "always meet in the middle" for cleaner close-pairs (deferred by the only-when-needed decision; revisitable).
