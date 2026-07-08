# Step 3 — Auto-performed stem dynamics (the DJ "mixing board") (design)

_Approved in conversation on 2026-07-08. The app stops laying a vocal on a flat, unchanging beat and starts **performing the beat** — sliding each of Song 1's stems (drums / bass / other) up and down over time, on the grid, the way a DJ works the deck. Built on `feat/house-bollywood-energy-sync`, additive on top of the working energy-synced arrangement (Steps 1–2)._

> **AS-BUILT NOTE (Wave 1 shipped 2026-07-08 — reality beats this document).** Two deliberate deviations from the design below, both found via the adversarial review and kept because they are simpler and provably safer:
>
> 1. **The engine sums the enveloped stems FIRST, then runs the original pipeline verbatim** — it does NOT carry the separate stems through the arrangement applying the build to `drums+other` while the bass is pulled separately. Each stem's gain envelope is applied and the three are summed into one bed; the bass pull is baked into that summed bed (its window equals the build window, so the effect is the same); then the pre-Step-3 build/breath/sweep + in-loop vocal placement run unchanged. This is what makes a no-move plan **byte-identical** to the old engine (proven, max abs diff 0.000) — the design's "linear equivalence" argument held for the stem sum but MISSED that deferring vocal placement changed how a later breath/sweep treats a prior vocal's tail; summing-first + keeping placement in-loop fixes that exactly.
> 2. **The never-all-muted guard is exact interval math (not sampling), and it REJECTS overlapping same-stem moves.** The engine multiplies overlapping same-stem envelopes, so a `min`-of-covering model could miss a hole; forbidding overlaps (Wave 1 never emits them) keeps the guard's per-move math exact and sound. `fence.stem_moves_for_drops` also takes the real downbeat grid (not bpm arithmetic) so the pull window lands exactly on downbeats.
>
> The invariants (one bassline, one vocal, on-beat, never clip/silent, old mixes identical) all hold as designed. `ENGINE_VERSION m5j.0`.

## The user job (why)

The founder's biggest recipe note (recipe §2.6, note 4): _"PRODUCE, don't assemble."_ Today the mix builds into each drop (filter + volume climb) but the beat underneath never moves — drums, bass and melody are fused into one layer the moment the mix is assembled, and nothing ever plays with them. A real house set breathes: the bass drops out on the build and slams back on the drop, it cuts to just the drums, the beat takes over, it breaks down and rebuilds. These are exactly the moves the **live player** already lets a human do by hand (mute / duck / beat-up / fade, built in M5) — Step 3 makes the **arrangement do them automatically**, at the app's own detected musical moments, on any pair. Without it the mix reads "too simple." The founder's north star (stated 2026-07-08): _the app plays with everything from the four stems, up to adding new beats._ This step builds the foundation that north star stands on.

## The one architectural principle (unchanged)

The brain plans a `MixPlan` (JSON); the deterministic engine executes the DSP; **the LLM never touches audio.** Step 3 adds one additive plan dimension (`stem_moves`) and one new engine capability (per-stem gain envelopes) to realise it. The referee still guarantees the hard rules against the real audio.

## The core idea — one primitive, four moves

Every DJ move in this step is the same primitive: **ride one stem's volume from A to B across an on-beat window, then return to full.** One `StemMove` type expresses all of them:

- **Bass pull-and-slam** (first to build) — `bass` ramps `1.0 → 0.0` across the build window into a drop; at the drop anchor it returns to `1.0` (the slam), on the beat, with the vocal.
- **Drop to just the beat** — `bass` and `other` held at `0.0` across a window (drums keep driving), then return.
- **Beat-up** — `other` (and a touch of `bass`) ducked so the drums dominate for a stretch.
- **Breakdown** — the bed stems ramped down to a low floor across a window, then rebuilt.

Boosting a stem above `1.0` is **out of scope for v1** (keeps clip-safety trivial — moves only duck/mute and return). "Adding new beats" and Bollywood-instrument accents are explicitly **later steps**, not this one.

## Data model (`app/models.py` — additive; old cached plans still parse)

- New `StemMove`:
  - `stem: str` — which Song-1 bed stem: `"drums" | "bass" | "other"`.
  - `start: float`, `end: float` — secs into Song 1, each on a downbeat (`start < end`).
  - `gain_from: float = 1.0`, `gain_to: float = 0.0` — linear gain ramp across `[start, end]`; the stem is at `1.0` everywhere outside any move. This single ramp expresses pull (`1→0`), hold-muted (`0→0`), duck (`1→0.4`), rebuild (`0→1`).
- `MixPlan.stem_moves: list[StemMove] = []` — top-level (a beat move isn't tied to a vocal entry). `[]` ⇒ today's behaviour exactly.

## The engine (`workers/render.py`, **dangerous surface**) — per-stem gain envelopes

- **Keep the three bed stems separate** (`drums`, `bass`, `other`) instead of pre-summing them into one bed. Each gets a **gain envelope** — a float array over the full length, initialised to `1.0`.
- **Apply each `StemMove`** to its stem's envelope: a linear ramp `gain_from → gain_to` across `[start, end]` in samples. A short **declick ramp** (`_STEM_SLAM_MS`, ~8 ms) smooths any gain discontinuity at a move's edges (so the `0 → 1` slam is crisp but never clicks) — the same click-hygiene the vocal edges already use.
- **Existing bed treatments move onto the stems:** the produced-drop **build** (`_build_bed`: low-pass sweep + volume climb) applies to `drums + other` over the build window while the `bass` stem is pulled by its `StemMove` (drums/melody open up as the bass sucks out → the slam). The plain-entry **breath duck** and **`sweep_in`** apply uniformly to all three stems over their bar, matching today's whole-bed behaviour.
- **Assemble:** `bed = Σ stem·envelope`, then the vocal placements and `s1_vocal_regions` are added on top exactly as today, then the unchanged peak-normalize (−1 dBFS) + brickwall clip guard.
- **Old-mix safety (linear equivalence):** with no `stem_moves` (all envelopes `1.0`) and treatments applied uniformly, summing the stems then filtering is mathematically identical to today's filter-the-summed-bed (LTI filters and gain ramps are linear: `f(a)+f(b) = f(a+b)`). So a plan without stem moves renders the same mix it does today — the "old mixes still work" invariant holds by construction, not by luck.
- Still decoupled (plain file paths); the 12-min decode cap and existing guards stay. Tunable-by-ear knobs stay named constants (`_BASS_PULL_FLOOR`, `_STEM_SLAM_MS`, the pull window = the existing `build_bars`).

## The brain (`app/planner/fence.py` + `plan.py`, safe surfaces) — decide where the moves go

- **`fence.stem_moves_for_drops(placements, bpm, build_bars, ...)`** — for each produced drop (a placement already carrying `build_bars`), emit one `bass` pull `StemMove` over that build window `[anchor − build_bars·bar, anchor]`, `1.0 → 0.0`. On-beat by construction (the anchor is a downbeat; the window is whole bars). The other three moves are added as sibling helpers in the follow-on wave (see Build order).
- **`plan.build_mix_plan`** calls it after `_produce_drops`, **only on a confident grid** (the same `_confident(a1)` gate that already guards build/echo — never perform fancy beat moves on shaky analysis; a shaky song keeps a plain, safe beat). Attaches `stem_moves` to the `MixPlan`.
- **Regenerate:** which drops receive a move can rotate by `take` for variety (kept minimal in the first wave; the bass-slam fires on every produced drop).
- The AI path is unaffected in wave 1 (deterministic placement of stem moves); giving Claude the option to choose moves is a later refinement behind the same fallback pattern.

## The referee (`app/planner/validate.py`, **dangerous surface**) — additive checks

`validate_plan` gains, for every `StemMove`:

- `stem` ∈ `{"drums","bass","other"}` — **fail loud** on anything else (like `_KNOWN_FX`: an unknown stem would silently do nothing, and this app's worst outcome is a quietly-worse mix).
- `start`/`end` each land on a Song-1 downbeat (R3), and `start < end`.
- `gain_from`, `gain_to` within `[0.0, 1.0]` (no boosts in v1 → the master can't be pushed into clip by a move).
- **Never-all-muted guard (defense-in-depth):** no instant has all three bed stems simultaneously ramped to ~0 (at least one bed stem stays audible) — so a bad plan can't punch a silent hole.
- **R2 (one bassline)** still holds by construction (only Song 1's bass exists; ducking it adds no second bass). **R6 (no clip / not silent)** on the real rendered audio is unchanged — the ultimate backstop that runs regardless of the plan.

## Route (`app/routes/mix.py`, safe) — no stale cache

Bump `ENGINE_VERSION` so no old-style cached mix is ever served for a plan that now carries stem moves. No new inputs (stem moves ride inside the plan; the engine already receives all four Song-1 stems).

## Invariants (the iron rules, and how each is held)

1. **One bassline** — only Song 1's bass, enveloped down and back; never two. ✅ by construction.
2. **One lead vocal** — stem moves add no vocals; the Step-1/2 vocal rules are untouched. ✅
3. **Every move on the beat** — stem-move boundaries snap to Song-1 downbeats; referee R3. ✅
4. **Never clip / never silent** — peak-normalize + clip guard; gains capped ≤ 1.0; never-all-muted plan guard; real-audio R6 backstop. ✅
5. **Old mixes still work** — `stem_moves` defaults `[]`; stem-separated assembly is linear-identical to today when envelopes are `1.0`. ✅

## Acceptance (how we'll know it worked)

On Father Ocean × Der Lagi (the free, cached test bench): into a big drop the **bass audibly drops away during the build and slams back on the beat with the vocal**, giving the drop real punch — checked against the finished audio (bass energy falls across the build then returns; no click at the slam; no clip; not silent) and the plan (moves on downbeats, one bassline, at least one stem always audible). A plan with no stem moves renders the **same** mix as before. The founder listens and we tune the pull depth / window by ear. Then the same engine lights up cut-to-just-drums, beat-up, and breakdown.

## Build order (two waves, one design)

- **Wave 1 (this implementation plan):** the `StemMove` model + the per-stem-envelope engine + the referee checks + `fence.stem_moves_for_drops` (bass pull-and-slam) + route bump + tests. Proves the mixing board and the highest-impact move end-to-end.
- **Wave 2 (fast follow, same primitive):** `fence` helpers for cut-to-just-drums, beat-up, breakdown, placed at section boundaries the app already detects. Small additions on the proven foundation — no new engine surgery.

## Dangerous surfaces (heavy path)

`workers/render.py` + `services/api/app/planner/validate.py` — additive, pre-launch. Route: independent test-author writes the failing tests first; a fresh adversarial-safety panel tries to prove it unsafe (could it clip? two basslines? a silent hole? break an old mix?); the founder gets a plain-language explanation and gives an explicit **yes**; the change is applied via confirm-and-apply (`.zuko/approve.js`); the founder listens. A fresh adversarial pass on the pre-existing R1 relaxation still runs before this branch merges to main (unchanged by this step).

## Tests (same PR; dangerous-file tests authored independently)

- `test_models` — `StemMove` additive; `MixPlan.stem_moves` defaults `[]`; an old plan JSON without it still parses.
- `test_fence` — bass pull emitted over the build window for a produced drop, on downbeats; none emitted when there's no drop or the grid is shaky.
- `test_plan` — `stem_moves` attached only on a confident grid; the bass move's window matches `build_bars`; a shaky song stays plain.
- `test_validate` — off-downbeat move flagged; unknown stem flagged; gain out of range flagged; all-three-muted flagged; a valid move passes.
- `test_render` — bass energy falls across the build then returns; the slam has no click; no clip; not silent; **a no-stem-move plan renders identically (within float tolerance) to the pre-change engine** (the old-mixes-still-work proof).
- `test_mix_route` — `ENGINE_VERSION` bumped.

## Out of scope (later)

Bollywood-instrument accents (recipe R4) · adding new external beats/loops (north-star; also brushes the V1 "no new music" non-goal — a deliberate future decision) · vocal chops on the drop (Step 4) · the AI taste layer (Step 5) · boosting stems above unity · the mix-cache eviction sweep (still the top pre-user-test backlog item).
