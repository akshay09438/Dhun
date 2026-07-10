# Prompt-DJ — How the Backend Works, End to End

_A plain-but-complete walkthrough of what the backend does, what it extracts from each song, the inputs we've hard-coded ourselves, and the logic from start to finish. Written for a technical person who wants to help make the product better. Every number and rule below is taken from the actual code (paths given), not a guess._

---

## 0. The one big idea (read this first)

**The AI plans; a deterministic engine executes. The AI never touches the audio.**

- The "brain" (an LLM, or a rules fallback) only ever outputs a **JSON recipe** — which vocal slice goes where, on which beat, with which effects. It never generates or edits a single audio sample.
- A separate, boring, **deterministic engine** reads that recipe and produces the sound with plain math (FFmpeg + numpy).
- A **referee** checks both the recipe _and_ the finished audio against hard quality rules before anything is served.

Why it's built this way: it keeps the audio predictable and testable, and it means a wrong AI decision can be caught by the referee instead of shipping a bad-sounding mix. **The worst outcome for this product is a bad-sounding mix**, so the whole design is arranged to prevent that.

**Buy-not-built:** the two genuinely hard AI jobs — separating a song into vocals/drums/bass and reading its beat grid — run in the **cloud (Replicate)**, because they can't run on the founder's machine. The clever "DJ judgment" is _our own_ code and is the real product.

---

## 1. The journey of one mix (the end-to-end pipeline)

Two songs go in (Song 1 = the beat/instrumental, Song 2 = the vocals). One mix comes out. Here is every stage:

| #   | Stage               | File                                                  | What happens                                                                                                                                                 | Cloud?  |
| --- | ------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| 1   | **Ingest**          | `routes/songs.py`, `audio/normalize.py`, `storage.py` | The uploaded file is decoded and **normalized** (44.1 kHz, stereo, peak brought to 0 dB) then stored under a **content hash** (its sha256) as its `song_id`. | no      |
| 2   | **Stem separation** | `audio/stems.py`                                      | The song is split into **4 stems** — vocals, drums, bass, other (melody) — by Demucs on Replicate. Cached by `song_id`.                                      | **yes** |
| 3   | **Analysis**        | `audio/analysis.py`                                   | We extract the **beat grid + structure** (cloud) and **key + energy + vocal map** (local math). Cached by `song_id`.                                         | partly  |
| 4   | **Plan**            | `planner/fence.py`, `planner/plan.py`                 | Given both songs' analysis, compute the legal/safe options, then decide the arrangement — a **MixPlan** (JSON).                                              | no      |
| 5   | **Check the plan**  | `planner/validate.py`                                 | The referee rejects a plan that breaks a hard rule _before_ we spend time rendering.                                                                         | no      |
| 6   | **Render**          | `workers/render.py`                                   | Deterministic DSP turns the MixPlan into one finished WAV.                                                                                                   | no      |
| 7   | **Check the audio** | `planner/validate.py`                                 | The referee reads the **real WAV** and rejects it if it's silent or clipping (analysis can lie; the audio can't).                                            | no      |
| 8   | **Serve / cache**   | `routes/mix.py`                                       | The finished mix is cached by a content id derived from (engine version + both songs + prompt + take), so an identical request is free.                      | no      |
| 9   | **Sets (optional)** | `workers/set_render.py`                               | Several finished mixes are stitched into one continuous set with crossfades.                                                                                 | no      |

Everything is **cached by content id** — a song is separated once, analyzed once; an identical mix renders once. Re-runs are free.

---

## 2. What we EXTRACT from each song (the analysis)

This is the raw material the whole product runs on. For each song we compute a `TrackAnalysis` (`models.py`), and — crucially — a **confidence score** rides along with every field, because _analysis being wrong is the enemy, not the rules_ (DJ Handbook Part 9).

| What we extract                                                  | Meaning                                                              | Where it comes from                                                                   |
| ---------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **bpm** + `bpm_confidence`                                       | tempo; confidence = how steady the beat grid is                      | cloud structure analyzer; confidence = local beat-regularity math                     |
| **beats**                                                        | the time of every beat                                               | cloud                                                                                 |
| **downbeats**                                                    | the "1" of every bar (load-bearing — every on-beat move trusts this) | cloud                                                                                 |
| **phrase_starts**                                                | every 8th downbeat (an 8-bar musical phrase; 4/4 assumed in V1)      | `downbeats[::8]`                                                                      |
| **key** (Camelot code) + confidence                              | musical key, e.g. "8A"                                               | local: chromagram + Krumhansl-Kessler profiles                                        |
| **sections** + `sections_confidence` (fixed 0.6 — the weak link) | labelled parts: verse / chorus / drop…                               | cloud                                                                                 |
| **energy_curve**                                                 | loudness (0–1) of **each bar** — the single most-used signal         | local: RMS per bar                                                                    |
| **vocal_regions** + `vocal_confidence`                           | the time spans where the singer actually sings                       | local: loudness of the **isolated vocal stem** per bar (so stems must be split first) |

**The cloud vs local split:** the beat grid, downbeats and sections come from a cloud model (`sakemin/all-in-one-music-structure-analyzer`). Key, energy and the vocal map are computed locally with numpy/scipy — they're free and don't need a GPU.

**Known weak spots in the extraction** (important for a helper):

- `vocal_regions` are often **coarse blobs** — a song that sings a lot can come back as _one_ giant region covering ~99% of the track, with no gaps. This blocks hook/lead detection and forces some songs to be used full-length.
- `sections` are the "industry-wide weak link" — trusted at only 0.6 confidence, never blindly.
- If a song is analyzed **before** its vocal stem exists, `vocal_regions` come back empty (a real trap we've hit); always split stems first.

---

## 3. The INPUTS we've given OURSELVES (curated data + tuned constants)

These are the human judgments and hand-tuned numbers baked into the code — the part that isn't computed from the audio. A helper improving the product will spend a lot of time here.

### 3a. Curated catalog + per-song hooks (hand-made)

- **The catalog** (`data/library/manifest.json`): a hand-verified list of songs we've already ingested, split and analyzed, chosen in a tempo band that blends well. Users pick from this list (V1 has no open upload in the shipped catalog flow).
- **The hook markers** (`planner/hooks.py`): for a few songs we **hand-mark the signature line** — the exact `(start, end)` seconds of "the hook" (e.g. Jee Karda's _"Jee karda"_ = 55.0–68.7 s). The app can't hear which line is the memorable one, so a human marks it (read off the section map, confirmed by ear). Only 3 are marked today; a song with no marker falls back to "loudest slice."

### 3b. Tempo safety (in `fence.py`)

- **Safe stretch band `0.89 – 1.11`** (±11%): how far we'll speed/slow Song 2's vocal to match the beat. Outside this it warbles, so we **decline the pair** instead of shipping it.
- **Movable-master bounds:** the house/beat track is the anchor; if a pair is too far apart, we nudge the house the _minimum_ — at most **4% slower / 8% faster** — and let the vocal absorb the rest.
- **Per-bar "grip" band `0.85 – 1.15`** (wider on purpose): used by the per-bar beat-lock, which makes tiny single-bar corrections that keep the vocal from drifting.

### 3c. Vocal-slice & hand-off shaping (in `fence.py`)

- Vocal slice length capped **4–40 s**; a "lead" passage must be **≥10 s** to count; a pre-drop "lick" is **1.5–4 s**; the two-vocal hand-off may overlap at most **1.2 s** (just long enough for the outgoing word to ring out under the incoming one).

### 3d. Energy thresholds (what counts as a "drop", a "build", etc.)

- A **drop** = a bar where energy is **≥0.6** _and_ rose by **≥0.15** over the previous 4 bars (a real low→high jump).
- **Beat-up** only fires in a stretch above energy **0.3**, ducking the melody to **0.4**.
- **Breakdown** ducks drums+bass down to **0.12** over **8 bars**.

### 3e. The "good-parts window" (in `planner/window.py`) — **DISABLED (full-song mixes)**

- Would target **~90 s** (flexible 60–120 s), ending ~**30 s** after the main drop, needing ≥**16 s** of run-up, plus a **12 s** wind-down outro. **Turned OFF 2026-07-09** (the founder chose full-song mixes after ear-testing) via a flag in `plan.py` (`_GOOD_PARTS_WINDOW_ENABLED = False`); the machinery is kept dormant + tested. Every mix is now the **whole song**.

### 3f. Render constants (in `render.py`)

- 8 ms edge fades (kill clicks); breath-duck to **0.35**; a produced-drop build starts at **0.55** volume and a **300 Hz** low-pass that opens up; echo = dotted-eighth delay, 4 decaying taps at **0.42** feedback; a vocal chop re-fires the first **0.22 s** every 8th note. Final master is peak-normalized to **−1 dB** with a hard clip ceiling.

### 3g. The engine version string

`ENGINE_VERSION` in `routes/mix.py` (currently `m5o.0`) is stamped into every mix's cache id, so improving the engine never serves a stale mix.

---

## 4. The BRAIN — how a mix is planned

Two layers: **the fence** (compute only legal, safe options) and **the driver** (pick an arrangement from them).

### 4a. The fence (`fence.py`) — "what's allowed"

Given both analyses it computes:

- **Shared tempo** (movable master) — folding octaves so a song read at half/double time still matches; declining if too far apart.
- **The house's real drops** — `energy_drops`, the low→high energy jumps.
- **Vocal slices / vocal peaks** — Song 2's longest and loudest sung stretches (with a fallback to labelled chorus/verse sections when the vocal map is blank).
- **The arc** — `synced_anchors`: split the song into thirds and put **one vocal entry in each third, preferring a real drop** in that third (so the vocal lands on the beat drop, and energy is spread across the whole song, not clustered).
- **Both vocals trading** — `lead_sections` (keep Song 1's own substantial sung passages in the gaps) and `predrop_licks` (keep Song 1's short vocal run _into_ a drop — "the vocal a DJ never cuts"). This is the "both lyrics" behavior.
- **The mixing-board moves** (`StemMove`s): the **bass pull-and-slam** into each drop, **drop-to-just-the-beat**, one **beat-up**, one **breakdown** — the beat _performs_ instead of sitting flat.
- **Per-bar beat-lock** (`warp_map`): instead of one global stretch, map each vocal bar onto the matching beat bar, so the vocal can't drift over a long placement.

### 4b. The driver (`plan.py`) — "pick one, two brains available"

`build_mix_plan` assembles the final **MixPlan**. There are **two ways** it can arrange:

- **The RULES engine** (`_default_arrangement`) — deterministic, hand-built DJ logic. Same songs → same mix, every time.
- **The AI engine** (`_ai_arrange`) — asks Claude to choose the arrangement. **Active whenever `ANTHROPIC_API_KEY` is set.**

> ⚠️ **Important, and a live product decision:** the two engines arrange _differently_, and the founder consistently prefers the **rules** engine (verified: a rules render is a note-for-note match to the loved reference; the AI render is measurably different and disliked). Right now the app uses the AI engine whenever the key is present. **Deciding whether to default to the rules engine is the single highest-value open call.** (See §9.)

---

## 5. The REFEREE — the quality guardrail (`validate.py`)

A dangerous surface that must never be removed. It checks the plan _and_ the finished audio. The hard rules:

- **R1 — one lead vocal at a time.** Song 1's vocal is excluded from the bed by construction; the arrangement's Song-2 placements must never overlap; and Song 1's own vocal may overlap Song 2 by at most the 1.2 s hand-off. Anything more = two voices fighting = rejected.
- **R3 — every vocal entry lands on a downbeat** (never mid-bar).
- **B3 — the tempo stretch stays inside the safe band** (no warble).
- **R6 — the real audio is neither silent/near-silent nor clipping.** Checked by reading the actual WAV, because a plan that looks fine can still render broken.
- **R7 — a beat-locked vocal re-locks cleanly** (every per-bar stretch in the grip band, every bar boundary on a downbeat).
- **Stem-move safety** — every beat move rides a real stem, lands on downbeats, only ducks (never boosts, so it can't push the master to clip), and **never mutes all three bed stems at once** (no silent hole — proven with exact interval math, not sampling).

The referee is deliberately an **independent** check: it re-derives the grid itself rather than trusting the plan's own numbers, so it can actually catch the plan being wrong.

---

## 6. The RENDER — turning the recipe into sound (`render.py`)

Deterministic DSP, step by step:

1. **Build the bed** = drums + bass + other, summed. _Song 1's vocal is simply never included — that is how "one vocal only" is guaranteed by construction._
2. **Movable master:** if needed, stretch the whole bed to the shared tempo first.
3. **Stem envelopes:** apply each `StemMove`'s gain ramp to its stem (this is where the bass pull-and-slam physically happens), then sum. _With no moves, this is byte-for-byte the plain bed — the "old mixes still work" invariant._
4. **Good-parts window:** crop the bed to the chosen window (fails **loudly** on a malformed window rather than shipping a beat-less mix).
5. **For each vocal placement:** cut Song 2's slice, stretch it to tempo (either one ratio, or the **per-bar warped** version), edge-fade it, optionally add a **build** (muffled→open filter + volume climb into the drop), a **breath duck**, a **sweep**, an **echo throw**, or a **chop** — then lay it on its anchor.
6. **Both vocals:** drop Song 1's own vocal passages into the gaps, played as recorded (its natural phrase-end decay is the blend into Song 2).
7. **Master:** peak-normalize to −1 dB and hard-clip at the ceiling, so the output **can never clip**.

---

## 7. SETS — stitching several mixes together (`workers/set_render.py`)

`assemble_set` joins finished mixes with an **equal-power crossfade** at each seam (peak-safe, clip-safe, any number of mixes). It's simple and forgiving.

> **Known limitation (opportunity):** the stitcher does **not tempo-match or beat-align** the seams — it's a plain crossfade. Mixes at slightly different tempos will have their beats clash through the transition. A real continuous DJ set needs tempo-locking + beat-alignment at the seams (prototyped but not yet in the product).

---

## 8. The safety net & why it's trustworthy

- **Content-addressed storage** (`storage.py`): every file is named by its own sha256, never by a user-supplied name — which neutralizes filename/path attacks and makes caching automatic.
- **Cache everything by content id:** split once, analyze once, render once.
- **Confidence + fallback ladder:** when analysis is shaky, the engine degrades gracefully (any downbeat → any beat; labelled sections when the vocal map is blank) instead of failing.
- **Dangerous surfaces** (guarded, reviewed extra-carefully): the upload handler, anything that deletes audio, `render.py`, and the `validate.py` referee.

---

## 9. Where a helper could make the biggest difference (honest open problems)

Ranked roughly by impact:

1. **AI-vs-rules arrangement.** The app uses the AI brain when the key is set, but the founder prefers the rules brain. Either default to rules, or **improve the AI arrangement** so it beats the rules. This is the #1 lever — it's why mixes have felt inconsistent.
2. **"The mixes feel too plain."** The founder's standing #1 quality gap: real remixes _process_ the vocal (EQ, reverb, energy outside the drop). Today we place clean stems; we don't "produce" the vocal. Big perceived-quality win.
3. **Set beatmatching.** The set stitcher is a dumb crossfade — no tempo-lock, no beat-align. Making continuous sets sound professional is a self-contained, high-value project.
4. **Coarse vocal detection.** `vocal_regions` come back as blobs. Better vocal segmentation (finer, phrase-level) would unlock cleaner hooks, cleaner "both-vocals" trades, and let more songs be windowed.
5. **Key/harmonic mixing is computed but unused.** `camelot_fit` exists but is only informational — the app only declines on tempo. Using key could improve which pairs blend.
6. **The good-parts window vs. both-vocals tension.** The ~90 s window makes clean transitions but is too tight for two dense vocals to trade — the two goals fight. A "longer-but-not-full" window is an open design problem.
7. **Section-map weakness.** Sections drive hook/lead/setup choices but are only 0.6-confidence. Better structure detection lifts a lot of downstream judgment.

---

_Source of truth is the code. If anything here disagrees with the code, the code wins — please flag it. Key files: `services/api/app/audio/{normalize,stems,analysis}.py`, `services/api/app/planner/{fence,plan,window,hooks,validate}.py`, `workers/{render,set_render}.py`, `services/api/app/{models,storage}.py`, `services/api/app/routes/{songs,mix,library}.py`._
