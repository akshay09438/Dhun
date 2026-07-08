# The House × Bollywood Recipe

**What this is:** the _taste_ the app must encode — the judgment that turns "a vocal sitting on a beat" into "a real DJ made this." Distilled from the founder's own 5 reference mashups (below), plus the DJ Judgment Handbook. This is the single source of truth for **what a good house × Bollywood mix sounds like**; the build plan ([house-bollywood-build-plan.md](house-bollywood-build-plan.md)) is how we teach the app to do it.

**Status:** DRAFT for founder review (2026-07-08). The general recipe (§2) is confirmed from our earlier sessions. The **per-song rules (§4) are my first draft — please correct anything wrong**; that's the one part only your ears can settle. No code changes until you approve.

---

## 1. The 5 reference mashups (the founder's taste, on record)

These are the mashups the founder chose as "this is what good sounds like." **All five are the same house track — _Father Ocean (Ben Böhmer Remix)_ — under a different Bollywood vocal.** That's the genre lane, proven by example.

| #   | Bollywood vocal                       | Reference mashup (YouTube)                  | In the app today?                                                                                            |
| --- | ------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 1   | **Tere Bina** (A.R. Rahman)           | https://www.youtube.com/watch?v=vgwL3W6gk-k | ❌ No — currently **declined** (too slow; the tempo fast-track is meant to unblock exactly this)             |
| 2   | **Der Lagi Lekin** (ZNMD)             | https://youtu.be/B2-7jIhnWoM                | ✅ Yes — in the catalog (key 10B, ~+10% stretch)                                                             |
| 3   | **Suniyan Suniyan** (Juss × MixSingh) | https://youtu.be/qYhT1DHIef4                | ❌ No — **dropped** for a key clash (C# maj ≈ 3B vs 10B). Tempo (130) is fine; the key needs V2 pitch-shift. |
| 4   | **Maula Mere Maula** (Anwar)          | https://youtu.be/8Yhq5qRs67s                | ❌ No — not ingested, but a **near-perfect match** (120 BPM, C maj ≈ 8B); should blend easily once added     |
| 5   | **Ji Karda** (needs ID)               | https://youtu.be/KWqpaPCDp6Q                | ❌ No — not ingested; several songs share this name (120 vs 140 BPM) — founder to confirm which              |

**A big, honest finding up front:** of these 5, **only Der Lagi Lekin is currently in the app**. The other four are the exact songs the app either declines, dropped, or has never seen. So these references aren't just "nice examples" — they're a to-do list. The recipe below is what to build; §5 says which of these five V1 can realistically reproduce and which need V2 (pitch-shift).

---

## 1.5 The tempo map (and why we don't nail everything to Father Ocean)

A key founder insight (2026-07-08): **it's not only the Bollywood song that has to move to catch up with Father Ocean — Father Ocean can slow down too, or the two can meet at a tempo in between.** The web BPM data confirms this is the right call. Father Ocean is **122 BPM**:

| Bollywood song   | Real BPM                            | Key          | If we lock it to Father Ocean (122) | If we meet in the middle                           |
| ---------------- | ----------------------------------- | ------------ | ----------------------------------- | -------------------------------------------------- |
| Der Lagi Lekin   | 111                                 | D maj (≈10B) | +9.9% (barely in band)              | ~116 → **±5% each** (cleaner)                      |
| Maula Mere Maula | 120                                 | C maj (≈8B)  | +1.6% (near-perfect)                | already matched                                    |
| Suniyan Suniyan  | 130                                 | C# maj (≈3B) | −6% (tempo is fine)                 | tempo fine; **key clashes** — needs V2 pitch-shift |
| Ji Karda         | 120 **or** 140 (ambiguous)          | —            | trivial / −13%                      | ~130 if it's the 140 version                       |
| Tere Bina        | ~144 (a ~72 ballad, double-counted) | D maj        | −15% → **declined today**           | ~133 → **±8% each — now in band!**                 |

**What this changes:** the app currently makes Father Ocean the immovable master and stretches only the vocal. That's why Tere Bina (−15%) is rejected. But if we pick a **shared target tempo between the two songs**, each moves only ~half as much:

- **Tere Bina becomes playable** — at ~133 each song moves only ~±8%, inside the safe band (vs an impossible one-sided −15%).
- **Every pair sounds cleaner** — Der Lagi at ~116 warbles half as much as at 122.

This is exactly how a real DJ sets a deck tempo _between_ two tracks. The cost: moving Father Ocean's tempo means time-stretching the whole house bed, not just the vocal — a bigger engine change (see the build plan's Step 1). It's worth it: it's what unblocks the founder's favourite pair.

---

## 2. The recipe (confirmed — the general rules for the genre)

Five rules, in the founder's own framing:

### R1 — Energy sync is the magic ⭐ (the most important one)

Line up the **Bollywood vocal's emotion** with the **house track's shape**:

- house **building up** → the vocal's **rising / soft** part
- house **drop / peak** → the vocal's **most powerful** part

Build-with-build, drop-with-peak. When the founder said the two Anchor-Point references felt "perfectly synced," _this_ is what they meant. This is the single thing that separates a real mix from a paste.

### R2 — On the drop, use vocal CHOPS + HUMS, not full verses

At the big house drop you don't play a whole sung line — you play **hook fragments and hums**, placed rhythmically ("dum da ra dum"). Short, punchy, on the grid. Full verses belong in the calmer stretches, not on the peak.

### R3 — The vocal rides both highs AND lows

The vocal isn't only for the loud parts. It breathes with the track — soft in the builds, powerful on the drops, sometimes stepping back to let the beat run. It follows the energy up and down.

### R4 — Bollywood _music_ can layer in as accents (but the house beat stays the floor)

A moment of the Bollywood song's **own instrumentation** (a flute line, a dhol hit, a string swell) can be layered _as an accent_ at the right moment — Maula Mere is the example the founder called out. **But the house/electronic beat is the constant foundation.** A DJ in this genre does **not** swap to the Bollywood beat. (This is the correction to the earlier "Song 2 plays as itself / beat-swap" plan — that move is wrong for this genre.)

### R5 — Clean switches, locked to the house build→drop

Every transition — vocal in, vocal out, accent in — lands on the house track's structure, specifically the **build→drop** moments. Nothing floats in at a random time. The house track's arrangement is the clock everything moves to.

### The iron rules that never break (unchanged, the quality floor)

1. **One bassline at a time** (the house beat's — no mud).
2. **One lead vocal at a time** (Bollywood or Father Ocean's own, never both — they trade).
3. **Every move lands on the beat.**
4. **Never clips, never silent.**
5. **Old mixes still work** (anything we add is additive).

---

## 2.6 What the FIRST real render taught us (founder ear-test, 2026-07-08)

The first energy-synced render (Father Ocean × Der Lagi Lekin) proved the app can FIND and HIT the house drops — the vocal landed on all three. But the founder's ears surfaced three things the recipe must now make explicit. These reprioritise the build and **correct the base architecture**:

1. **Clean vocal in/out — land in the GAPS between phrases, NEVER mid-word.** Today a slice starts/ends on a downbeat (and, when vocal-regions are missing — as they were for Der Lagi — on a crude section edge), so it cuts between words: "dirty." Slices must begin and end where the singer is actually silent (phrase boundaries), with fades that hide the seam. This is an "ears" upgrade (real vocal-phrase detection) + edge craft.

2. **USE BOTH vocals — do NOT strip Father Ocean's own vocal, especially into its drop.** ⚠️ **This corrects the base architecture.** Father Ocean is an EDM track WITH a vocal that builds into its drop ("some vocal comes, then the drop comes"). Stripping it and laying only the Bollywood vocal over an instrumental **loses the song**. The right model: the **house track plays largely AS ITSELF** (its own vocal + build + drop), and the **Bollywood vocal is WOVEN IN and TRADES with it** (one lead at a time — iron rule 2). At Father Ocean's own drop, keep Father Ocean's vocal; bring the Bollywood vocal in at OTHER moments (or as a chop). So Song 1's vocal is a **real, central part**, not stripped — the engine's current "instrumental bed + one guest vocal" is wrong for this genre.

3. **Real ENERGY DYNAMICS — builds, risers, ups and downs — not a flat beat with 3 vocal drops.** The mix must climb: filter opens, energy rises into the drop, breakdown, slam back. A constant beat with three placements reads as "simple." This is the build/filter craft.

4. **PRODUCE, don't assemble — perform the mix with all four stems + FX.** ⭐ The biggest note: the app must _make mood music_, not lay a vocal on a beat. It should **play with all four stems** (drums/bass/melody/vocals) against each other over the song — drop to just the beat, pull the bass, bring the melody up — **throw FX** (echo/delay throwbacks on a vocal tail into the drop, reverb, filter sweeps), and **ride the levels** (louden a hook line or a beat for impact). This is exactly the moves the LIVE player already lets a human do by hand (mute/solo/duck/beat-up/fade) — now the arrangement must do them AUTOMATICALLY, plus FX, across the whole song. The brain decides the moves (JSON), the deterministic engine executes the DSP (architecture unchanged; the LLM never touches audio). Without this the mix is "just very plain."

### The moves palette (what "producing" means, concretely)

Each is a discrete, buildable engine capability (all FFmpeg/numpy — no new libraries), decided by the brain and executed deterministically:

- **Both-vocals weave** — Song 1 and Song 2 vocals trade the lead (one at a time), Father Ocean's vocal kept into its own drop.
- **Clean vocal edits** — enter/leave in the phrase gaps, fades hide the seam.
- **Vocal FX** — echo/delay throwbacks (esp. the last word before a drop), reverb tails.
- **Filter builds & sweeps** — lowpass opening up into a drop, risers, the climb.
- **Stem dynamics (auto-performed)** — drop-to-just-the-beat, pull/return the bass, melody up/down, beat-up — the live moves, automated at musical moments.
- **Level rides / emphasis** — louden a hook line or a beat for impact.
- **Vocal chops / hums on the drop** — hook fragments placed rhythmically ("dum da ra dum").

**What was fair to judge in the Phase-A render, and what was not:**

- ✅ FAIR: did the vocal hit the drop? (yes) — and the honest gut check "does this feel like a real mix?" (not yet — fairly).
- ⏳ NOT YET BUILT (not failures — the next steps): clean word-boundary edits, both-vocals weaving, energy dynamics/builds, vocal chops, and Tere Bina.

---

## 3. What "the app listens to the music" actually means

The founder's push — _"the app has to listen to the music"_ — resolves like this: **the app's own perception is the listening.** It already hears the beat, the key, and the loudness of every bar. What it can't yet do is name the **builds, the drops, and the vocal's peak moments** — and that naming is exactly what powers energy-sync (R1). So "listening" is a buildable feature (energy detection), not magic. Claude plans over what the app hears; the founder's ears are the final judge.

(Claude can't hear audio directly — so the founder's narration + running the references through the app's analysis is how their taste becomes numbers the planner can use.)

---

## 4. Per-song rules (⚠️ MY DRAFT — founder to correct)

> **Read this section as a first draft, not fact.** I reconstructed each from the confirmed recipe (§2) + what these tracks are + the app's own data where we have it. Your original per-song feedback didn't survive in our written records, so **please fix anything wrong** — this is the part only your ears know. Where it says _"[app analysis pending]"_ I'll replace the guess with real numbers once you okay running that reference through the app (see §5).

### 1. Tere Bina × Father Ocean — the emotional slow-burn

- **Why it works (draft):** Tere Bina is a soaring, emotional Rahman vocal. The pull is a big powerful chorus landing on Father Ocean's drop, with the tender verses riding the builds. This is the founder's **#1 favourite pair.**
- **The catch:** ~144 BPM (a ~72 BPM ballad the detector double-counts) — outside the band when locked to Father Ocean's 122, so the app **declines it today.** The fix is the **movable-master tempo** (§1.5): meet at ~133, so each song moves only ~±8% (in band) instead of an impossible one-sided −15%. Some warble is expected on such a stretch.
- **App data:** ~144 BPM, D major (web). Precise vocal-entry timing [app analysis pending — needs ingest].

### 2. Der Lagi Lekin × Father Ocean — the clean anchor

- **Why it works (draft):** key-compatible (D major ≈ 10B, same family as Father Ocean) and a modest tempo move, so the blend is clean with no pitch tricks. A confident, safe pair — good for proving the recipe first.
- **App data:** in the catalog — 111 BPM, key 10B. **Blendable today** (+9.9% locked to 122, or a cleaner ~±5% if we meet at ~116). This is the pair I'd prove the recipe on first.

### 3. Suniyan Suniyan × Father Ocean — ⚠️ honesty flag (key, not tempo)

- **Why it works (draft):** an airy, melodic Punjabi vocal that sits pretty over melodic house.
- **The catch — important, and corrected:** the problem is **the key, not the tempo.** 130 BPM is perfectly fine against 122 (−6%, well in band). But the key is **C# major (≈3B)** against Father Ocean's 10B — a hard clash. Father Ocean can't be pitch-shifted in V1, so a clean blend of the _real_ keys isn't possible yet. **The reference mashup almost certainly pitch-shifted one song** — a **V2** capability for us. So this one is **aspirational for V1**: attempting it is honest evidence that the pitch-shift engine (already a V2 note) is what unlocks the Bollywood-heavy catalog.
- **App data:** 130 BPM, C# major (web). Confirm by app analysis.

### 4. Maula Mere Maula × Father Ocean — the accent showcase (a near-perfect match!)

- **Why it works (draft):** this is the reference where the **Bollywood song's own music layers in as an accent** (R4) — a moment of its instrumentation over the house floor, not just the vocal. The founder called this out specifically as the "accents" example.
- **App data:** 120 BPM, **C major (≈8B)** — and here's the good news: 120 BPM ≈ Father Ocean's 122 (a ~1.6% nudge), and C major (8B) is **harmonically compatible** with Father Ocean's 10B (two steps on the clock, same letter). **This should blend beautifully in V1 with no tempo tricks at all** — likely the easiest of the five. (A "Maula Mere Maula 122 BPM" edit already exists in the wild — DJs pair these constantly.) Needs ingesting into the catalog.

### 5. Ji Karda × Father Ocean — ❓ needs identification

- **Why it works (draft):** a driving, catchy hook — likely a strong candidate for the **chop-on-the-drop** move (R2), where the hook fragment lands rhythmically on the peak.
- **The catch:** several different songs are called "Ji Karda / Jee Karda" (Singh is Kinng ~120 BPM; Badlapur ~140 BPM; others). **I can't tell which one you used** — founder to confirm, or the reference audio will settle it. If it's the 120 version it's trivially matched; if 140, meet at ~130 (±7% each, in band).
- **App data:** [needs identification + ingest].

**Founder:** correct any of the five above — especially anything about _which move_ each one showcases (energy-sync? chops? accents?), since that's what becomes the app's rulebook.

---

## 5. Which references V1 can realistically reproduce (honest)

| Reference        | V1 reproducible?            | What it needs                                                                                   |
| ---------------- | --------------------------- | ----------------------------------------------------------------------------------------------- |
| Maula Mere Maula | ✅ Yes, easily              | Near-perfect match (120 BPM, C maj ≈ 8B) — just ingest it; showcases the accent move (R4)       |
| Der Lagi Lekin   | ✅ Yes, today               | Already in the catalog — prove the recipe here first                                            |
| Tere Bina        | 🟡 Yes, with movable-master | Meet at ~133 (§1.5) so each song moves only ~±8% — unblocks the founder's favourite             |
| Ji Karda         | ❓ Needs identifying        | Confirm which "Ji Karda"; then ingest + analyze                                                 |
| Suniyan Suniyan  | 🔴 Likely V2                | Tempo is fine (130) — the **key** clashes (C# maj vs 10B); a clean blend needs pitch-shift (V2) |

**Recommended proving order:** Der Lagi Lekin (in-catalog, clean) → Maula Mere Maula (ingest; near-perfect, shows accents) → Tere Bina (movable-master, the founder's favourite) → Ji Karda (once identified) → Suniyan Suniyan last (may prove the V2 pitch-shift case).

---

## 6. Getting the hard numbers (the "run it through the app" step)

To replace the _[app analysis pending]_ guesses above with real data, we can pull each reference's audio and each source song's audio and run them through the app's existing analysis. That gives objective **build times, drop times, and vocal-entry timings** for each reference — turning the founder's taste into numbers the planner can copy.

- **What it costs:** each song is analyzed in the cloud (Replicate) — a few cents each; ~10 songs total. Also needs the audio downloaded from YouTube and the engine running with keys.
- **Recommendation:** do this **after** the founder approves this recipe's framing (no point measuring against a framing that might change), and confirm the small credit spend first.

---

_This document writes no code and changes nothing until the founder approves it. It is a document to read and react to — change anything._
