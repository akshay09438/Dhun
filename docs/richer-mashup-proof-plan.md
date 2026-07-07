# Richer Mashup — Build Plan (the "Prove It" version)

**Status: DRAFT FOR FOUNDER REVIEW. No code will be written until you read this and say go.**
Date: 2026-07-08 · Branch it will land on: a new branch off `feat/m5-live-control`

---

## 0. The one-line goal

Turn **one** Bollywood × techno mashup from _"too simple — just a vocal over a beat"_ into _"whoa, a real DJ made this"_ — then re-show it to the 3–4 people who said V0.1 sucks. If they feel the difference, the judgment path is proven and we roll it out. If not, we learned it cheaply.

This is a **proof on one pair**, not a full rollout. We keep the scope tight on purpose.

---

## 1. Why the current mix feels "too simple" (grounded in the real code)

I mapped exactly how a mix is made today. Here's the honest picture:

- The engine (`workers/render.py`) builds the mix as **Song 1's beat (drums + bass + other) with Song 2's vocal laid on top**. That role is hard-wired in two lines — Song 1 is _always_ the beat, Song 2 is _always_ just the vocal.
- Song 1's _own_ vocal can answer briefly in the gaps ("contrast"), but only as a background whisper, never as a real part of the song.
- **Song 2's own beat is never used. Song 2 never plays as itself.** So really only _one_ song is ever fully present — the other is reduced to a vocal floating over it.

That's the root of "too simple": **it's one trick — one beat, one borrowed vocal — repeated across the whole song.** No matter how we arrange it, only one song is truly in the room.

## 2. The idea — a 3-act mini DJ set of the two songs

Instead of one flat layer, the mix becomes a short **journey** that clearly uses _both_ songs, the way a DJ would:

- **Act 1 — Open on Song 1.** Song 1's beat plays; Song 2's vocal weaves in on the beat (like today, but landing cleanly).
- **Act 2 — The switch (the new hero moment).** A clean DJ transition **swaps the beat** so **Song 2 plays as itself** — its _own_ beat, bass, and vocal — for a stretch. This is the moment a listener goes _"oh, both songs are really here."_ Then it swaps back.
- **Act 3 — Build to a peak.** A rising filter/energy build leads into the strongest final entry, then a clean outro.

Two iron rules the whole time (these are what stop it sounding like mud):

- **One bassline at a time.** When Song 2's beat takes over, Song 1's beat steps _out_ (we replace, not stack). Never two low-ends fighting.
- **One lead vocal at a time.** Song 1 and Song 2 never sing lead together — they trade.

**The single most important new thing is Act 2 — the beat swap into "Song 2 as itself."** That one move is what flips "too simple." Everything else (the build, the cleaner weave) is supporting polish.

## 3. Scope of THIS proof

**Must-have (the thing that proves it):**

1. **Song 2 plays as itself for one section** — its own beat + bass + vocal — with a clean bass-swap transition in and out. (The Act-2 hero move.)

**Should-have (makes it land):** 2. A **build to the peak** before the final entry (extend the existing filter-sweep into a real build). 3. **Cleaner vocal placement** — make sure Song 2's vocal is detected reliably so entries land on the right spot (a small "ears" fix).

**Deferred (NOT in this proof — noted so we're honest):**

- Swapping in a whole new beat-detection model ("Beat This!"). It's the real long-term "better ears" upgrade, but it's a big integration and the _current_ detector already reads our demo pair's beat correctly — so it is **not needed to prove richness.** We do the cheap ears fix now and revisit the model swap later.
- Full free-form vocal trading across many sections, multi-song sets, pitch-shift, any generative/AI-audio model. All later.

**The pair we prove on:** the known-good anchor — **Father Ocean × Don't Start Now** (Don't Start Now is the one vocal already confirmed clean). We prove on the _easiest_ pair first; hard pairs come after the concept is proven.

---

## 4. What changes, file by file (the technical steps + imports)

Good news up front: **we add no new libraries.** Everything reuses the tools already in the app (FFmpeg, numpy, soundfile, scipy). We're teaching the existing machine new moves, not bolting on new machinery.

Files marked **🔒 protected** are on the "handle with care" list — they get the extra safety review and your explicit yes before any edit (see §6).

### 4.1 The ears — `services/api/app/audio/analysis.py` _(safe surface)_

- **What:** make vocal detection more reliable so entries land on the real singing. Today a bar counts as "vocal" only if it's ≥25% as loud as the loudest vocal bar; we lower/soften that threshold and make it robust when the vocal stem is quiet.
- **Imports:** none new.
- **Why:** placements that land on the actual vocal feel intentional, not random.
- **Note:** the brain already falls back to song sections when detection is empty, so this is a refinement, not a rewrite.

### 4.2 The recipe models — `services/api/app/models.py` _(safe surface, additive)_

- **What:** add a new small model `BeatSegment` = `{ source, start, end, warp }` and a new optional list `MixPlan.beat_segments: list[BeatSegment] = []` — the timeline windows where Song 2 plays as itself. `source` says whose beat drives the segment (for the proof: `"song2"`). `warp` beatmatches Song 2's own beat onto Song 1's grid.
- **Imports:** none new (`pydantic.BaseModel` already imported).
- **Why additive is safe:** every model is plain Pydantic with defaults, so **old cached mixes still load** and nothing else breaks.

### 4.3 The fence (arrangement math) — `services/api/app/planner/fence.py` _(safe surface)_

- **What:** add a function that picks _where_ the "Song 2 as itself" segment goes — aligned to a Song 1 section boundary and a strong Song 2 chorus, snapped to downbeats — and computes the `warp` to lock Song 2's beat to Song 1's tempo (reusing the existing `warp_map` logic).
- **Imports:** none new (already imports `TrackAnalysis`).

### 4.4 The brain — `services/api/app/planner/plan.py` _(safe surface)_

- **What:** in `build_mix_plan`, after the vocal placements are chosen, decide **one** beat-segment (Song 2 as itself) for a confident pair, and attach it to the plan. Update the DJ-language `notes`. On a shaky pair, skip it (play safe) — same pattern as the existing "flourishes" logic.
- **Imports:** none new (already imports `fence`, `llm`, models).

### 4.5 The engine — `workers/render.py` 🔒 _(protected)_

- **What (the core new DSP):**
  - `render_mix` gains an optional `song2_stems` input (Song 2's own drums/bass/other/vocals).
  - A new helper renders a **"Song 2 as itself" block**: Song 2's own beat + bass + other + vocal, tempo-matched (warped) to Song 1's grid, edge-faded.
  - In the main render, for each beat-segment we **replace** that stretch of Song 1's bed with the Song 2 block, joined by **equal-power crossfades** at both boundaries (the clean bass swap). Replace — never layer — so there's only ever one bassline.
  - Extend the existing `_sweep_bed` filter sweep into a slightly longer **build** before the final entry.
- **Imports:** none new (numpy, soundfile, scipy, subprocess already there).
- **Reuses:** the existing `_vocal_take_warped`, `_edge_fade`, `_hold`, `_sum_stems`, crossfade helpers — no duplicated DSP.

### 4.6 The referee — `services/api/app/planner/validate.py` 🔒 _(protected)_

- **What:** teach the rulebook about the new segment so it can never ship a bad mix:
  - **One bassline (R2):** beat-segments must not overlap each other; within a segment Song 1's bed is replaced (checked by construction).
  - **One lead vocal (R1):** a Song-2-as-itself segment must not overlap a Song-2 vocal placement or a Song-1 contrast region.
  - **On the beat (R3):** each segment boundary lands on a Song 1 downbeat.
  - **In-band tempo (R7):** the segment's warp stays inside the safe stretch band.
- **Imports:** none new.

### 4.7 The route wiring — `services/api/app/routes/mix.py` _(safe surface)_

- **What:** pass Song 2's own stems into `render_mix`, and bump `ENGINE_VERSION` (e.g. `m4d.1 → v1.0-djset`) so no stale "old-style" mix is ever served from cache.
- **Imports:** none new.

### 4.8 The tests _(Python tests are a safe surface here)_

- New tests, written **before** the code, by an independent reviewer (see §6):
  - a Song-2-self segment renders (its beat is present in that window, Song 1's is not);
  - only one bassline at a time; only one lead vocal at a time;
  - segment boundaries land on downbeats; warp stays in band;
  - the finished audio doesn't clip and isn't silent (existing R6 still passes);
  - old cached plans (no `beat_segments`) still render unchanged.

---

## 5. The invariants we must never break

No matter what the arrangement does, the finished mix must always satisfy — and the rulebook (`validate.py`) checks the real audio, not just the plan:

1. **One bassline at a time** (no mud).
2. **One lead vocal at a time** (no clash).
3. **Every switch lands on the beat.**
4. **No clipping, never silent.**
5. **Old mixes still work** (nothing we add breaks what exists).

## 6. How we'll build it safely (the process)

Because this touches the **mixing engine and the rulebook** (the app's quality guardrails), it goes the careful route:

1. You read and approve **this document**. ← we are here
2. An **independent reviewer writes the tests first**, from the goal above — before any code, so the tests aren't shaped to fit the code.
3. I build it in small pieces; after each, the automatic safety net runs.
4. Before the two protected files (`render.py`, `validate.py`) are changed, a **panel of fresh reviewers** tries to prove it's _unsafe_ (could it clip? two basslines? two vocals? break old mixes?). It's cleared only if all of them pass.
5. I explain the protected change to you in plain words and ask your explicit **yes** before applying it (I apply it — you never touch code).
6. You **listen** to the result. Your ears are the real gate.

## 7. How we'll know it worked (your test sheet)

1. Open the app, pick **Father Ocean** + **Don't Start Now**, make the mix.
2. **Listen for the switch:** partway through, Song 2 should take over with _its own beat and vocal_, then hand back to Song 1 — a clean swap, no mud, no clash, on the beat.
3. **Listen for the build:** energy should rise into the final entry, not stay flat.
4. **The real test:** show it to the same 3–4 people. Do they go from "too simple" to "oh, that's actually good"?
5. **Pass = we roll the moves out to the rest of the catalog. Fail = we learned cheaply and rethink.**

## 8. What we are NOT doing (non-goals for this proof)

- No generative / AI-audio model (it can't mix your real songs and it kills live steering).
- No new beat-detection model yet (deferred; not needed to prove richness).
- No multi-song sets, no pitch-shift, no free-form vocal trading everywhere.
- No touching the upload handler, storage, secrets, or CI.
- Not proving on every pair — one known-good pair first.

## 9. Decisions I need from you before we start

1. **Direction OK?** Is the "3-act mini DJ set, with Song 2 playing as itself in the middle" the right richer mix to prove?
2. **Ears scope OK?** Agree we do the _cheap_ vocal-detection fix now and defer the big beat-model swap?
3. **Pair OK?** Prove on **Father Ocean × Don't Start Now** first (the known-clean pair)?

---

_This plan writes no code and changes nothing until you approve it. It's a document to read and react to — change anything you like._
