# House × Bollywood — Build Plan (the energy-sync version)

**Status: PHASE A BUILT (energy-sync, safe surfaces) — awaiting founder ear-test. Phase B (protected engine) not started.**
Date: 2026-07-08 · Branch: `feat/house-bollywood-energy-sync` (off `feat/m5-live-control`)
Companion doc: [house-bollywood-recipe.md](house-bollywood-recipe.md) (the taste this plan encodes)

> **Build progress (2026-07-08):**
> - ✅ **Step 2 (energy detection)** — done, derived purely from the cached energy curve (no `analysis.py` change, no re-analysis). `fence.energy_drops` / `fence.vocal_peaks`.
> - ✅ **Step 3 (energy-sync arrangement)** — done. `fence.synced_anchors` + `plan._default_arrangement` now land Song 2's loudest vocal peak on Song 1's biggest drop; AI path is energy-sync-aware too. **191 backend + 39 web green, TDD.** Verified on the real Father Ocean × Der Lagi pair (4 drops detected, every vocal on a drop).
> - ⏸️ **Step 1a+1b (movable-master tempo), Step 4 (chops), Step 5 (build), Step 6 (accents)** — Phase B, deferred (protected engine), gated behind founder ear-test of Phase A + confirm-and-apply.

> This **replaces** the earlier `richer-mashup-proof-plan.md`, whose "Song 2 plays as itself / beat-swap" hero move was **wrong for this genre**. In house × Bollywood the **house beat stays the constant floor** — you do not swap to the Bollywood beat. The real hero move is **energy sync** (§2).

---

## 0. The one-line goal

Turn a house × Bollywood mix from _"too simple — just a vocal over a beat"_ into _"whoa, a real DJ made this"_ — by making the app **line the Bollywood vocal's emotion up with the house track's builds and drops**, chop the vocal onto the drops, and stop rejecting slow songs. Then re-show it to the 3–4 people who said V0.1 sucks.

This is a **proof on a few pairs**, not a full rollout. Scope stays tight on purpose.

---

## 1. Why the current mix feels "too simple" (grounded in the real code)

I mapped exactly how a mix is made today:

- The engine ([`workers/render.py`](../workers/render.py)) lays **Song 2's vocal on top of Song 1's beat**, with the vocal spread across the song in an **energy arc** — but the arc is ranked by **loudness only** ([`fence.arc_anchors`](../services/api/app/planner/fence.py)). It places the vocal where the song is loudest; it does **not** know what a _build_ or a _drop_ is, so it can't line the vocal's power up with the music's power.
- The vocal is always played as a **whole sung slice** — never chopped into hooks/hums for a drop.
- Slow songs are **declined** ([`fence.legal_options`](../services/api/app/planner/fence.py)) rather than sped up — so the founder's favourite (Father Ocean × Tere Bina) never even builds.

So "too simple" has three concrete roots: **no energy-sync, no chops, and good pairs getting rejected.** This plan fixes those three, in that order.

---

## 2. The idea — energy-synced, chopped, and never-rejected

Instead of "spread the vocal by loudness," the mix becomes an **energy-synced journey**:

- The app **detects the house track's builds and drops** and the **vocal's peak moments** (new "listening").
- It **lines them up** (R1): the vocal's soft/rising parts ride the house _builds_; the vocal's most powerful part lands on the house _drop_.
- On the **drop**, instead of a whole verse, it places a **vocal chop/hum** (R2) — a hook fragment on the grid.
- Instead of nailing every song onto Father Ocean's tempo, the app picks a **shared tempo between the two** (movable master) so neither warbles much — so slow pairs like Tere Bina can play at all instead of being rejected.
- Optionally, a moment of the **Bollywood song's own music layers in as an accent** (R4) — later in the sequence.

The house beat stays the floor the whole time. The iron rules (one bassline, one lead vocal, on-beat, no clip, old mixes still work) hold throughout — checked against the real audio by the referee ([`validate.py`](../services/api/app/planner/validate.py)).

---

## 3. Scope — build in this order (each is its own gated step)

Ordered cheapest-and-safest first, so we unblock the founder's favourite pair early and only touch the "handle with care" files once the safe groundwork is proven.

| Step                                     | What                                                                                  | File(s)                       | Dangerous?          | Unlocks                               |
| ---------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------- | ------------------- | ------------------------------------- |
| **1a. Common target tempo**              | Pick a shared tempo _between_ the two songs (not always Father Ocean's)               | `fence.py`                    | No (safe)           | Halves the stretch on both songs      |
| **1b. Movable master (stretch the bed)** | Stretch the whole house bed to that target, not just the vocal                        | `workers/render.py`, `mix.py` | 🔒 **Yes**          | Father Ocean × Tere Bina plays at all |
| **2. Energy detection**                  | Label the house track's **builds / drops** and the vocal's **peaks**                  | `analysis.py`, `models.py`    | No (safe, additive) | The app can "hear" energy             |
| **3. Energy-sync arrangement**           | Place the vocal so its power lines up with the house drops (R1); soft parts on builds | `fence.py`, `plan.py`         | No (safe)           | Build-with-build, drop-with-peak      |
| **4. Vocal chops / hums on drops**       | Chop the vocal into hook fragments and place them on the drop (R2)                    | `workers/render.py`           | 🔒 **Yes**          | The "dum da ra dum" moment            |
| **5. Build / filter craft**              | Extend the filter sweep into a real rising **build** before a big entry (R5)          | `workers/render.py`           | 🔒 **Yes**          | The lift into the drop                |
| **6. (Later) Bollywood accents**         | Layer a moment of Song 2's own instrumentation as an accent (R4)                      | `render.py`, `validate.py`    | 🔒 **Yes**          | Maula Mere-style accents              |

Steps 1a, 2, 3 are safe surfaces and deliver most of the "whoa" (energy-sync is the magic). Steps 1b, 4–6 touch the engine/referee and go the full careful route (§6).

> ### ⭐ Recommended sequence (after a product pressure-test, 2026-07-08)
>
> An independent product review pushed back on building all six steps at once — the point of a proof is to learn fast, and four of the six touch the protected engine. Its recommendation, which I agree with:
>
> **Phase A — prove the magic on safe surfaces only:** Step **1a → 2 → 3** (target-tempo math + energy detection + energy-sync arrangement). **No protected-engine edits at all.** Plus one free win: **ingest Maula Mere Maula** (120 BPM, key-compatible — a clean pair for the price of an upload, no engine risk).
>
> - Re-test on **Der Lagi Lekin + Maula Mere Maula** (both clean, no engine risk). If energy-sync alone flips the "too simple" testers, we've proven the core lesson without touching a single quality guardrail.
>
> **Phase B — only if Phase A lands:** open the engine for **Step 4 (chops)**, then **Step 5 (build)**, then **Step 1b (movable master, for Tere Bina)** and **Step 6 (accents)** last.
>
> **Why defer chops and movable-master:** chops ("dum da ra dum") are a sophisticated move — done slightly wrong they sound _broken_ to a casual ear, not impressive; prove them as a second bet. And movable-master touches the protected render path to unblock **one** pair (Tere Bina) — worth doing, but a casual creator cares that _some_ good pairs exist, not that pair specifically. Maula gives us a second clean pair for free; Tere Bina can wait until the safe wins are proven.
>
> **Founder's call:** Tere Bina is your favourite and your emotional proof — if you'd rather see it early, we can move Step 1b up. This is a recommendation, not a lock.

---

## 4. What changes, file by file (grounded in the current code)

**No new libraries** — everything reuses FFmpeg, numpy, soundfile, scipy, already in the app. Files marked 🔒 are on the "handle with care" list (extra review + your explicit yes before any edit — §6).

### Step 1 — Movable-master tempo (the founder's tempo insight)

Today the app makes **Father Ocean the immovable master** and stretches only the vocal onto its 122 BPM. That's why Father Ocean × Tere Bina is declined: locking Tere Bina's ~144 onto 122 is a −15% one-sided stretch, outside the safe band. **A DJ instead picks a tempo _between_ the two tracks so neither warbles much** — at ~133, each song moves only ~±8% (in band). See the recipe's tempo map (§1.5 there).

**Step 1a — Common target tempo · `services/api/app/planner/fence.py` _(safe surface)_**

- **What today:** `best_stretch` folds octaves and picks the ratio closest to 1.0, then `legal_options` **declines** anything outside the ±11% band ([fence.py:32](../services/api/app/planner/fence.py), [fence.py:168](../services/api/app/planner/fence.py)).
- **What changes:** compute a **shared target tempo** for the pair — one that keeps _both_ the house stretch and the vocal stretch inside the safe band (roughly the tempo between them). If such a tempo exists, the pair is mixable even when locking-to-122 would have declined it. Return the target + both stretch ratios.
- **Design care:** keep the referee's `SAFE_STRETCH_LO/HI` (used by R7 in `validate.py` 🔒) **unchanged** — we're not loosening the per-bar tolerance, we're choosing a smarter target so both stretches _already_ fit inside the existing tight band. This keeps Step 1a on a safe surface.
- **Imports:** none new.

**Step 1b — Stretch the house bed to the target · `workers/render.py` 🔒 + `routes/mix.py`**

- **What today:** the engine sums Song 1's stems at their native 122 and only stretches the vocal.
- **What changes:** when the target tempo isn't Father Ocean's own, `atempo`-stretch the **whole house bed** (drums + bass + other) to the target, and rescale its grid (downbeats) by the same factor, before placing the vocal. The existing per-bar warp/beat-lock then operates on the already-retimed grid, so nothing downstream needs to know. One added stretch step; reuses existing FFmpeg helpers.
- **Why it's protected:** it changes the master render path — hence the full careful route (§6). The referee still checks the real audio (one bassline, on-beat, no clip) regardless of the target tempo.
- **Imports:** none new.
- **Simpler fallback if we want to defer 1b:** a one-sided vocal stretch with a slightly wider _curated-pair-only_ allowance (kept out of the referee's default) still unblocks moderate pairs, but it can't cleanly reach Tere Bina — so 1b (movable master) is the recommended, correct version.

### Step 2 — Energy detection · `analysis.py` + `models.py` _(safe surfaces, additive)_

- **What today:** [`analysis.py`](../services/api/app/audio/analysis.py) computes an `energy_curve` (loudness per bar) and `sections`, but nothing names a **build** (a rising run) or a **drop** (a low→high jump into a sustained peak), and the vocal map has no notion of a **peak** moment.
- **What changes:** compute, from the existing `energy_curve` + `downbeats` + `sections`, three additive fields: **`builds`** (rising energy runs), **`drops`** (phrase starts where energy jumps and stays high), and Song 2's **`vocal_peaks`** (its loudest sung stretches). Pure arithmetic over data we already have. New optional model fields on `TrackAnalysis` (additive, defaulted → old cached analyses still load).
- **Imports:** none new.

### Step 3 — Energy-sync arrangement · `fence.py` + `plan.py` _(safe surfaces)_

- **What today:** `arc_anchors` spreads the vocal by **loudness bands only**; `plan.build_mix_plan` picks slices without regard to whether the vocal moment is soft or powerful.
- **What changes:** a new fence function pairs **Song 2's vocal peaks → Song 1's drops** and **Song 2's soft/rising parts → Song 1's builds** (R1), snapped to downbeats. `plan.py` uses it to choose placements (with the existing deterministic fallback + `take` rotation for Regenerate). The AI driver gets the builds/drops/peaks in its payload so it can arrange with the same intent; the deterministic path guarantees energy-sync by construction if the AI misbehaves.
- **Imports:** none new.

### Step 4 — Vocal chops / hums on drops · `workers/render.py` 🔒 _(protected)_

- **What:** a new helper chops a vocal peak slice into short **hook fragments** and places them **on the drop's grid** (R2) — tempo-matched (warped) to Song 1's beat, edge-faded, click-free. Reuses the existing `_vocal_take_warped`, `_edge_fade`, `_hold`, crossfade helpers — **no duplicated DSP.** `MixPlan` gains an additive `chops` description (old plans without it render exactly as today).
- **Imports:** none new.

### Step 5 — Build / filter craft · `workers/render.py` 🔒 _(protected)_

- **What:** extend the existing `_sweep_bed` filter sweep into a slightly longer **rising build** before a big vocal entry (R5) — a filter opening + energy lift, gain-safe. A refinement of a move already in the engine, not a new machine.
- **Imports:** none new.

### The referee · `services/api/app/planner/validate.py` 🔒 _(protected — touched by Steps 4–6)_

- **What:** teach the rulebook about chops and accents so a bad mix can never ship:
  - **One lead vocal (R1):** chops/accents must not overlap another lead-vocal placement or Song 1's contrast region.
  - **On the beat (R3):** every chop/accent boundary lands on a Song 1 downbeat.
  - **In-band tempo (R7):** any warped fragment stays inside the safe stretch band (the tight default — the fast-track's wider band is a Step-1 planning allowance, not a referee relaxation).
  - **No clip / not silent (R6):** unchanged, still checked on the real audio.
- **Imports:** none new.

### Route wiring · `services/api/app/routes/mix.py` _(safe surface)_

- Pass any new inputs through and **bump `ENGINE_VERSION`** so no stale old-style mix is ever served from cache.

### Tests _(Python tests are a safe surface here)_

- Written **before** the code by an independent author (§6): fast-track speeds up a slow pair instead of declining; energy detection labels builds/drops/peaks on a known curve; the arrangement lines a vocal peak onto a drop; chops land on downbeats and stay in-band; one lead vocal / one bassline always; no clip / not silent; **old cached plans still render unchanged.**

---

## 4.5 The user-facing side (don't forget the screen)

The steps above are all engine-side (invisible arrangement). Two user-facing things must not get lost:

- **The prompt / "steer it with words" promise.** This recipe is **hardcoded taste for the Father Ocean lane** — quality becomes largely automatic. That's fine for validation, but we name it honestly: this is _"one great preset for one genre lane,"_ **not yet "describe any mix."** Decision needed: does the user's typed prompt still nudge the arrangement (e.g. "more vocal", "keep it chill"), or is it fully automatic for now? Either is OK — but we say which, and don't overclaim reach. (Honest framing: all 5 references are the _same_ house track, so this is really **"the Father Ocean recipe,"** not a general House × Bollywood engine. Correct for a curated-shelf proof.)
- **Regenerate ("give me another take") — a named V1 job.** Energy-sync _pins_ the vocal's power to fixed drops, so takes could all start to feel the same. The plan rotates the slice/window by `take`, but we must **decide up front what actually varies on regenerate under energy-sync** (which drop the peak lands on, which vocal slice, whether a chop vs a full line) — or we'll fix "too simple" and quietly break "give me another one."

Neither needs a new screen — both are about keeping an existing promise true as the engine gets smarter.

---

## 5. The invariants we must never break

The finished mix must always satisfy these — and the referee checks the **real audio**, not just the plan:

1. **One bassline at a time** (the house beat's — no mud).
2. **One lead vocal at a time** (Bollywood or Father Ocean's own — they trade).
3. **Every move lands on the beat.**
4. **No clipping, never silent.**
5. **Old mixes still work** (everything added is additive/defaulted).

---

## 6. How we'll build it safely (the process)

Steps 1a, 2, 3 are safe surfaces (still tests-first + reviewed). Steps 1b, 4–6 touch the **mixing engine and rulebook** (the app's quality guardrails), so they go the careful route:

1. You read and approve **this plan + the recipe.** ← we are here
2. An **independent reviewer writes the tests first**, from the recipe's rules — before any code, so tests aren't shaped to fit the code.
3. I build in small pieces; the automatic safety net runs after each.
4. Before the protected files (`render.py`, `validate.py`) change, a **panel of fresh reviewers** tries to prove it _unsafe_ (could it clip? two basslines? two vocals? break old mixes?). Cleared only if all pass.
5. I explain each protected change to you in plain words and ask your explicit **yes** before applying it (I apply it — you never touch code).
6. You **listen.** Your ears are the real gate — ideally on **Father Ocean × Tere Bina** and **× Der Lagi Lekin**.

---

## 7. How we'll know it worked (your test sheet)

1. Open the app, pick **Father Ocean** + **Der Lagi Lekin** (the clean pair), make the mix.
2. **Listen for energy-sync:** the vocal's soft parts should ride the builds and its most powerful part should hit right on the drop — not float in at random.
3. **Listen for the chop:** on a big drop, a hook fragment / hum should land on the beat, not a whole verse.
4. Pick **Father Ocean** + **Tere Bina** — it should now **make a mix at all** (the movable master meets them at a shared tempo). Listen for warble; a little is expected on such a stretch, but far less than a one-sided speed-up.
5. **The real test:** re-show the 3–4 people who said "too simple." Do they go to "oh, that's actually good"?
6. **Pass = roll the moves out across the catalog. Fail = we learned cheaply and rethink.**

---

## 8. What we are NOT doing (non-goals for this proof)

- **No generative / AI-audio model** (it can't mix your real songs and it kills live steering).
- **No new beat-detection model yet** (Beat This! is the later "better ears" upgrade; the current detector reads our pairs correctly, so it's not needed to prove the recipe).
- **No pitch-shift** — which means **Suniyan Suniyan may not blend cleanly in V1** (honest: its key clashes; a clean version likely needs the V2 pitch-shift engine). We'll attempt it and let the result make the V2 case.
- **No beat-swap** (the corrected move — the house beat stays the floor).
- No multi-song sets, no touching the upload handler, storage, secrets, or CI.
- Not proving on every pair at once — the clean in-catalog pair first, then the movable-master pair.

---

## 9. Decisions I need from you before we start

1. **Recipe right?** Does the [recipe](house-bollywood-recipe.md) — energy-sync + chops-on-drops + accents, house beat as the floor — match what you hear in your 5 references? (Correct the per-song notes in §4 of the recipe.)
2. **Movable master OK?** Agree the tempo strategy is "meet at a shared tempo between the two songs" (which means gently stretching Father Ocean too), not "always speed the Bollywood song up to 122"? This is what unblocks Tere Bina.
3. **Sequence OK?** Agree to the recommended **Phase A first** (energy-sync on safe surfaces + ingest Maula → re-test), and only open the engine for chops / movable-master in **Phase B** if Phase A lands? (Or move Tere Bina's movable-master up if you want your favourite early.)
4. **Cheapest de-risk before ANY build:** the review's best idea — show a few _cold_ (not-your-friends) casual creators one of your 5 reference mashups next to today's app output and ask "would you post this?" If the recipe itself doesn't pull a "yes," no engine work will. Want me to help set that up?
5. **Run the references through the app now?** Okay to spend a few cents of cloud credits to pull each reference's + source song's hard build/drop/vocal-entry numbers (fills the _[app analysis pending]_ gaps and settles which "Ji Karda" it is)? I'd do it right after you approve the framing.
6. **Which "Ji Karda"?** Confirm the song (Singh is Kinng? Badlapur? something else?) or I'll settle it from the reference audio.
7. **Which pair do we prove on first?** I suggest **Der Lagi Lekin** (in-catalog, clean) → **Maula Mere Maula** (near-perfect, once ingested) → **Tere Bina** (your favourite, via the movable master).

---

_This plan writes no code and changes nothing until you approve it. It's a document to read and react to — change anything you like._
