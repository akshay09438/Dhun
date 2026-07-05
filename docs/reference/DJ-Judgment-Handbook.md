# The DJ Judgment Handbook

**What this is:** a plain-language rulebook of how skilled DJs think and decide, turned into concrete "if this, then do that" rules that can be coded as the product's judgment layer. Every rule is written so it can be checked against a track's analysis (beatgrid, key, sections, vocal positions, energy) and fired at a specific beat.

**How to read it:** the user says *what* ("add drums," "bring in song two"). This handbook decides *when* (which beat) and *how* (which move, how long, what to cut). That decision layer is the product. This is its brain.

The brain has **three layers**, and all three must be built for V1 to survive real songs and real-time use:
1. **The DJ rules** (Parts 1–8) — what a good decision *is*, assuming the analysis is correct and there's time to act.
2. **Analysis confidence & fallback** (Part 9) — what to do when the data is *wrong or shaky* (the beatgrid, key, or sections can't be trusted).
3. **Live command orchestration** (Part 10) — how real-time prompts *queue, override, get delayed, or get declined* when they arrive too fast, conflict, or land too late to honor cleanly.

Parts 1–8 are the craft. Parts 9–10 are what keep the craft from breaking in the wild. Skipping 9 and 10 is the single most common reason a demo that works on your three curated songs falls apart the moment someone uploads their own.

**Source basis:** synthesized from DJ software makers and manuals (Pioneer DJ, DJ.Studio, Serato workflows), the origin of harmonic mixing (Mixed In Key / the Camelot system), and established DJ-education outlets (DJ TechTools, MusicRadar, Digital DJ Tips, Club Ready DJ School, Point Blank Music School, Mixgraph, SetFlow). Full source list at the end.

---

## Part 1 — How DJs actually think

A DJ's job splits into two kinds of work:

- **Mechanical work** — beatmatching, gain matching, cueing, EQ moves. This is *rules and math*. It can be automated. This handbook makes it explicit.
- **Judgment work** — *when* to switch, *which* move, *how much* tension, *where* the set is going. This is taste and context. Most of it is still rules DJs can articulate; the rest is feel. We encode the rules; we let the AI pick among the "legal" options for the feel.

The mental model a good DJ carries: **keep the floor moving, tell a story with tension and release, and never let a switch sound accidental.** A transition sounds *intentional* when the two tracks' musical structures line up (same point in the bar, same kind of section) and *clean* when their frequencies don't collide (one bassline, one lead vocal). Almost every rule below serves one of those two goals: **intentional** and **clean**.

The most important reframing for the product: **DJing is music understanding + music editing, not "crossfading songs."** The value is converting intent into structure-aware, frequency-aware, energy-aware decisions.

---

## Part 2 — The counting system (the foundation everything stands on)

All timing rules depend on counting music. In the 4/4 time signature that governs almost all dance, pop, and hip-hop:

- **Beat** = one pulse (the thing you tap your foot to).
- **Bar (measure)** = 4 beats.
- **Phrase** = a group of bars, almost always **8 bars = 32 beats** (sometimes 16 bars). This is the single most important unit in DJing. Western dance music is built in blocks of 8, 16, and 32 counts, and the human ear *expects* changes to land on those boundaries.
- **Downbeat / "the one"** = the first beat of a bar. The **phrase-start downbeat** (the "one" that begins a new 8- or 16-bar block) is where nearly every good move happens.
- **Section / stage** = a labeled chunk of the song: intro, verse, chorus (or "drop" in electronic), breakdown, buildup, bridge, outro. Sections are made of phrases.

**Typical section lengths** (defaults when analysis is uncertain): intro 16 bars, outro 16 bars, verse 16 bars, chorus 32–64 counts, breakdown 8–16 bars.

**Genre modifiers** (adjust phrase expectations):
- House: steady, predictable 8-bar phrases.
- Techno: longer, evolving phrases; needs longer transitions.
- Drum & bass: ~170–180 BPM; decisive 8- or 16-bar transitions, not long blends.
- Amapiano: ~108–115 BPM; spacious, percussion-heavy.
- Hip-hop / pop: shorter phrases (8–16), and sometimes irregular (6- or 10-bar) — count carefully, don't assume 8.

**Product rule 0 (the master anchor):** *Every action fires on a beat from the analyzed beatgrid — never at the raw millisecond the user pressed enter. The default anchor is the next phrase-start downbeat. Cheaper moves (effects) may fire on the next bar-start downbeat. Nothing fires mid-bar unless explicitly a "cut now" command.*

---

## Part 3 — What the product must know about each track (analysis inputs)

The judgment rules can only run on this data. Compute it once per track, before play:

1. **BPM** and a full **beatgrid** (timestamp of every beat).
2. **Downbeats** (which beats start bars) and **phrase-start downbeats** (which start 8/16-bar phrases).
3. **Musical key**, expressed as a **Camelot code** (e.g. 8A). Minor = A, Major = B.
4. **Section map**: intro / verse / chorus-drop / breakdown / buildup / outro, with start/end beats.
5. **Vocal-presence timeline**: where lead vocals are singing (to avoid vocal clash).
6. **Energy curve** (0–1 over time) — not the same as BPM; it's density + drive + bass weight + vocal presence.
7. **Stems** (drums / bass / vocals / other), pre-split, so layers can be added/removed instantly on the beat.

---

## Part 4 — The Rulebook

Rules are grouped by pillar. Each is written as **Condition → Action → Parameter**. "Snap" always means "move to the nearest/next matching beat in the grid."

### A. Timing & phrasing rules (decide WHEN)

**A1 — Bring the new track in on a phrase.** *Condition:* user wants to introduce a new track or a big new element. *Action:* snap the entry to the next **phrase-start downbeat** of the track currently playing. *Why:* the ear expects change on phrase boundaries; landing there is what makes a mix feel intentional.

**A2 — Match like sections ("stage matching").** *Condition:* both tracks' section maps are known. *Action:* prefer to align the *same kind* of section — verse over verse, chorus over chorus, breakdown over breakdown, intro over outro. *Why:* the arrangements reinforce instead of fight; energy doesn't dip unexpectedly.

**A3 — Respect the chorus.** *Condition:* the outgoing track is in a vocal chorus/drop. *Action:* do NOT start the incoming track's chorus/vocal over it. Time it so the incoming track's *verse or beat-only intro* takes over as the outgoing chorus ends. *Why:* two choruses = two vocals shouting over each other.

**A4 — Use beat-only intros/outros as the mix zone.** *Condition:* incoming track has a percussion-only intro, or outgoing has a beat-only outro. *Action:* prefer these as the overlap window. *Why:* no melody means nothing to clash; solves most beginner transition problems automatically.

**A5 — Breakdowns are free transition windows.** *Condition:* either track has a breakdown (8–16 bars, little/no percussion). *Action:* treat it as a natural gap — bring the other track's beat in underneath, or mix out through it. *Why:* the missing percussion leaves room; the crowd barely notices.

**A6 — Don't overstay.** *Condition:* a track has been playing a long time / the user is looping content. *Action:* offer/prepare the next transition around the next outro or breakdown rather than playing full length. *Why:* playing every track full-length bores the floor.

**A7 — Handle irregular phrasing.** *Condition:* detected phrase length isn't 8/16 (e.g. 6- or 10-bar pop/disco), or confidence is low. *Action:* fall back to counting from the last detected section change; widen the "acceptable entry" window; prefer a short cut over a long blend. *Why:* long blends expose phrasing errors; short moves hide them.

### B. Tempo & beatmatching rules (SYNC)

**B1 — Match tempo before overlapping.** *Condition:* two tracks will play together. *Action:* time-stretch one (or both) to a common BPM; align beatgrids so downbeats coincide. *Why:* different tempos drift apart into a mess.

**B2 — Preserve pitch when stretching (key lock).** *Condition:* changing a track's tempo. *Action:* use tempo-change that keeps pitch constant (key lock / repitch off). *Why:* a naive speed change detunes the track (chipmunk/slow-mo effect).

**B3 — Small stretch = safe; big stretch = don't blend.** *Condition:* the two BPMs are far apart. *Action:* if the required stretch is large, do NOT attempt a long beatmatched blend — large speed changes create audible glitch/warble artifacts. Instead use one of: a short 1-bar cut; an **echo-out**; a **loop** of the outgoing track adjusted to the new tempo; a **"meet in the middle"** (move both toward a midpoint, then commit); or a **double-time** move if the new track is ~2× the BPM. *Why:* the stretch artifacts are worse than a clean cut.

**B4 — Bigger tempo gaps favor shorter transitions.** *Condition:* moderate BPM gap. *Action:* shorten the overlap length. Fast genres (DnB) prefer decisive 8/16-bar switches over long blends regardless of gap.

### C. Harmonic / key rules (Camelot)

Camelot: 24 keys on a clock, 1–12, letter A = minor (darker), B = major (brighter). Relative major/minor share the same number (8A ↔ 8B).

**C1 — The four safe moves.** *Condition:* a long melodic blend is planned. *Action:* only overlap melodic content if the incoming key is one of: **same key**; **±1** on the same letter (e.g. 8A→7A or 9A); **A↔B at the same number** (relative major/minor mood flip); or **+2** (energy boost). *Why:* these share most notes and sound consonant. Larger jumps risk clashing.

**C2 — Key matters most on long melodic blends, least on quick/percussive moves.** *Condition:* transition is a quick cut, a breakdown swap, or two percussion-driven tracks with little melody overlapping. *Action:* relax the key constraint. *Why:* if the melodies barely overlap, dissonance has no room to appear. Don't block a great-for-the-moment move just because keys differ.

**C3 — Pitch-shift only in small amounts.** *Condition:* forcing two tracks into a compatible key by pitch-shifting the incoming one. *Action:* keep the shift to ±1 semitone. *Why:* larger shifts create unnatural timbre/vocal artifacts.

**C4 — Use key direction for mood.** *Condition:* user asks to lift or darken. *Action:* A→B (minor→major) or a +2 / +7 (one semitone up) move to **brighten/lift**; move toward minor (B→A) or step down the wheel to **darken**. *Why:* upward key motion feels like uplift; the +7 (add 7 to the Camelot number) is the classic pop key-change lift.

**C5 — Energy-boost jumps must be quick.** *Condition:* doing a +2 or dissonant-but-cool jump for excitement. *Action:* keep the blend short; don't let melodies overlap long. *Why:* it's an effect, not a smooth blend; a long overlap exposes the tension.

### D. Frequency / EQ / bass-swap rules (keep it CLEAN)

Three bands: **Low** (~20–200 Hz: kick + bass), **Mid** (~200 Hz–5 kHz: vocals + melody + body), **High** (~5–20 kHz: hats, claps, cymbals, air).

**D1 — Never play two basslines at once (the #1 rule).** *Condition:* two tracks overlap. *Action:* keep only ONE dominant low end at any moment. Cut the incoming track's low fully while it enters; **swap the bass on a phrase-start downbeat** — bring the new low up as the old low comes down, cleanly. *Why:* two lows collide into muddy, distorted sub on a real system (phase cancellation / mud).

**D2 — Bring highs first, then mids, then lows.** *Condition:* an EQ-swap blend. *Action:* fade in the incoming track top-down — highs first, mids next, lows last — and pull the outgoing track's bands in the same order. *Why:* the top end blends invisibly; the low end is the dangerous part, so it's handed over last and fast.

**D3 — To emphasize an element, cut others (don't boost).** *Condition:* user says "bring the bass up" / "make X stand out." *Action:* prefer *cutting the competing bands* over boosting the target band. *Why:* boosting eats headroom and risks clipping; cutting achieves the same balance cleanly.

**D4 — Don't zero the same band on both tracks.** *Condition:* both tracks playing. *Action:* never fully kill the same frequency band on both at once. *Why:* the mix needs energy in every band; killing both lows (or both highs) sounds hollow and wrong.

**D5 — Mid cuts are gentle, not kills.** *Condition:* clashing mids (e.g. two melodic/vocal tracks). *Action:* reduce the outgoing mid *partially* to make room, don't fully kill it. *Why:* vocals/instruments span multiple bands, so a full mid-kill just makes a weird muffled version rather than removing them.

**D6 — Gradual = smooth, instant = dramatic.** *Condition:* choosing EQ behavior. *Action:* ramp EQ over ~16 bars for a seamless morph; use an instant "kill" for a deliberate dramatic moment. *Why:* two different tools for two different intents.

**D7 — Return EQ to neutral (no EQ creep).** *Condition:* after a move that pushed a band away from center. *Action:* ease it back toward neutral over the following bars. *Why:* leaving bands parked off-center accumulates into a lopsided, wrong-sounding mix.

### E. Vocal rules

**E1 — Never layer two lead vocals.** *Condition:* both tracks have lead vocal at the overlap window. *Action:* mute/duck one vocal stem during the overlap, OR move the switch point to where only one track has vocal. *Why:* two singers at once is chaos — the fastest way to sound amateur.

**E2 — A vocal entry can be a peak.** *Condition:* user wants a big moment. *Action:* time a vocal drop to land on a phrase-start downbeat after a beat-only or instrumental section. *Why:* the human voice arriving after a gap is one of the strongest lifts available.

**E3 — Acapella over instrumental is a premium move.** *Condition:* one track can be reduced to vocals (stem) and the other to instrumental. *Action:* lay the isolated vocal over the other's instrumental — but only if keys are compatible (C1) since the vocal's pitch is now exposed. *Why:* it sounds like a bespoke remix.

### F. Transition-type selection (choose WHICH move)

This is the decision framework. Given the two tracks' key/energy/section state, pick the move:

**F1 — Compatible keys + similar energy → long blend.** Let the two grooves overlap for many bars (16–32). The harmonic alignment makes an extended overlap sound musical.

**F2 — BPMs match but keys clash → quick cut OR filter sweep.** The cut avoids overlap entirely; the filter sweep strips the clashing melodic content and leaves only rhythm/texture.

**F3 — Big energy shift (up or down) → filter sweep OR echo-out.** Both create a buffer between two energy levels so the jump isn't jarring.

**F4 — A usable breakdown exists → breakdown swap.** Bring the incoming beat in under the outgoing breakdown; when the breakdown resolves, you're already on the new track. Premium when keys are compatible and energy matches.

**F5 — Large BPM gap → cut / echo-out / loop / double-time** (see B3).

**F6 — Default when unsure → beat-only-intro blend on a phrase boundary with a bass swap** (A1 + A4 + D1). This is the safe, always-acceptable move.

### G. Effects rules

**G1 — Less is more.** *Condition:* any effect request. *Action:* apply sparingly and time-boxed to the transition; one effect at a time. *Why:* effects should serve the mix, not announce themselves. Overuse is a classic tell of an amateur.

**G2 — Effects land on the beat and clear on the beat.** *Condition:* adding reverb/delay/echo/filter. *Action:* start on a downbeat, set delay/echo times to musical divisions (1-beat, 1/2-beat), and remove the effect on a downbeat (typically before the incoming drop, "on the one"). *Why:* off-grid effects smear the timing.

**G3 — Echo-out recipe.** *Condition:* ending the outgoing track, especially across a big gap. *Action:* on the outgoing track, apply a building echo/reverb (optionally over a short loop) through the last bars, drop its volume to leave just the tail, then drop the incoming track on the next phrase-start downbeat. *Why:* it's the "drum-roll before the crash" — tension then release. Don't use it at peak energy (it deflates the room); save it for moments where a pause serves the story.

**G4 — Filter sweep for tension and for clash-avoidance.** *Condition:* building tension, or blending clashing tracks. *Action:* sweep a low-pass (muffle) or high-pass (thin) over 4–16 bars; open/close it across the transition. A high-pass on the outgoing track is a more extreme, cleaner bass-remover than the low EQ. *Why:* removes problem frequencies while adding drama.

**G5 — Bass-cut lifts and tension.** *Condition:* user wants a lift or a build. *Action:* a **1–2 bar** bass cut right before a phrase change = a small lift; an **8-bar** bass cut = a tension-building mini-breakdown; drop the bass back on the downbeat. *Why:* dancers instinctively react to the bass dropping out and slamming back in.

**G6 — Silence is a tool.** *Condition:* just before a big drop. *Action:* a beat (or half-beat) of near-silence resets attention and makes the next drop explosive. *Why:* contrast. Use rarely.

### H. Energy & set-arc rules (decide DIRECTION)

Energy is **not** BPM. A 126-BPM track with heavy bass, tight groove, and a vocal hook is far higher energy than a 126-BPM track that's sparse and vocal-free. Score energy from density, drive, bass weight, and vocal presence.

**H1 — Shape an arc, don't play random bangers.** *Condition:* a continuous session. *Action:* maintain an intended energy shape. Default shapes: **Journey** (start ~3–4, build to peak 8–10, resolve to 3–4), **Peak-time** (relentless high), **Warm-up** (start low, hand over warm), **Cool-down** (bring it down), **Chill** (steady low). *Why:* crowds respond to narrative, not individual tracks.

**H2 — Think in thirds.** First third establishes vibe/tempo/mood (the first few tracks set expectations). Middle third builds. Final third peaks and resolves — save the strongest/"anchor" tracks for here.

**H3 — BPM creep.** *Condition:* building energy. *Action:* raise tempo gradually, ~1–3 BPM per transition. *Why:* individually imperceptible, but after several tracks the floor feels the lift.

**H4 — Genre/family stepping.** *Condition:* shifting energy. *Action:* move through adjacent families (e.g. deep house → house → tech house → techno to lift; the reverse to ease). *Why:* natural energy gradients.

**H5 — Don't peak too early.** *Condition:* early in a session. *Action:* hold back the biggest moments and the hardest bass/vocal drops. *Why:* the most common amateur mistake; peaking early leaves nowhere to go.

**H6 — Waves, not a plateau.** *Condition:* sustained high energy. *Action:* insert release — a breakdown, a groovier track, a bass-cut breather — between peaks. *Why:* constant 10/10 means nothing hits; contrast makes peaks feel earned.

**H7 — Long blends build sustained energy; short cuts sharpen peaks.** *Condition:* choosing overlap length by intent. *Action:* use long overlapping blends to build hypnotic momentum; use short, punchy cuts approaching a peak moment.

**H8 — Match direction to intent words.** *Condition:* user says "take it up / darker / calmer / keep it going." *Action:* map to concrete moves — *up* = +BPM creep, brighter key (→B or +2), higher-energy track, add layers; *darker* = minor key (→A), remove a layer, LPF, lower-energy selection; *keep going* = maintain energy, prioritize smooth same-energy transitions.

### I. Loudness / gain rules

**I1 — Never redline.** *Condition:* always. *Action:* keep the master and channels in the green/amber; never sustained red. *Why:* clipping is square-wave distortion that no mastering can fix.

**I2 — Match perceived loudness across tracks.** *Condition:* tracks from mixed sources. *Action:* normalize/gain-match so no track jumps out; don't fully trust automatic gain — verify against a loudness target. *Why:* consistent level keeps the mix professional and protects headroom.

**I3 — Normalize the final output.** *Condition:* rendering/exporting a continuous mix. *Action:* apply loudness normalization to a target and a brickwall limiter to catch peaks. *Why:* a consistent, clean master.

### J. "Don't" rules (hard guardrails — the fast tells of a bad mix)

- **J1** Don't play two basslines at once (see D1).
- **J2** Don't stack two lead vocals (see E1).
- **J3** Don't start a mix mid-phrase without a reason (see A1).
- **J4** Don't slam a low-energy intro over a peak chorus (kills the floor).
- **J5** Don't redline (see I1).
- **J6** Don't overuse effects (see G1).
- **J7** Don't attempt a long beatmatched blend across a huge BPM gap (see B3).
- **J8** Don't ignore the room/intent — if the user redirects, abandon the planned arc.

---

## Part 5 — The transition-type catalog (with parameters)

Each move, when to use it, and the parameters the engine needs.

| Move | Use when | Anchor | Length | Key needs | Bass handling | Effects |
|---|---|---|---|---|---|---|
| **Beat-only-intro blend** (default safe) | Incoming has percussive intro | Phrase-start downbeat | 8–16 bars | Loose | Bass swap on a phrase | Optional light filter |
| **Long harmonic blend** | Compatible key + similar energy | Phrase-start downbeat | 16–32 bars | Strict (C1) | Gradual bass swap | Minimal |
| **Quick cut** | Key clash, or big BPM gap, or fast genre | Phrase or bar downbeat | <1 bar | Ignore | Hard hand-off | Optional 1-beat echo to smooth |
| **Bass swap** | Any overlap (component of most blends) | Phrase-start downbeat | 4–8 bars | Same-key ideal | The whole point | — |
| **Filter sweep** | Tension, energy shift, or clash-avoid | Phrase or bar | 4–16 bars | Relaxed | HPF can replace bass EQ | LPF/HPF is the effect |
| **Echo-out** | Ending track, big gap or big energy shift | Drop incoming on "the one" | Last 2–8 bars | Relaxed | Outgoing fades to tail | Echo/delay + optional loop |
| **Breakdown swap** | Either track has a breakdown | Bring beat under breakdown | 8–16 bars | Ideal if melodic overlap | Incoming beat first | Light reverb to glue |
| **Double-time** | Incoming ≈ 2× outgoing BPM | Phrase-start downbeat | Short | Relaxed | Swap on drop | Faster cut works best |
| **Layer add/remove** (stem) | User adds/removes drums/bass/vocal live | Next bar or phrase | 2–4 bar fade | Bass→C1/D1, vocal→E1 | Enforce single-bass, single-vocal | Optional |

---

## Part 6 — The master decision framework (what the product runs on every command)

When the user types a command, run this pipeline:

1. **Interpret** the words into an intent + target (AI): what element, what direction, what track. ("add drums" → un-mute drums stem of the active track; "bring in song two" → introduce Track B; "make it darker" → energy-down + key-toward-minor.)
2. **Pick the anchor beat** (rules): default = next phrase-start downbeat of the currently playing track (Rule 0, A1); effects may use next bar downbeat; explicit "now" = next beat.
3. **Choose the move** (F1–F6): based on key relationship (C1/C2), energy relationship (H8), BPM gap (B3), and whether a breakdown/beat-only window is available (A4/A5).
4. **Apply the clean-up constraints** (D + E): enforce single bassline (D1), single lead vocal (E1), top-down EQ order (D2), no double-band kill (D4).
5. **Set parameters:** overlap length (by intent/energy, H7), fade curves, EQ ramp (D6), key-shift if needed (C3), effect timing (G2).
6. **Check guardrails** (J): if the move violates a hard "don't," fall back to the safe default (F6) and, if two options are both legal, let the AI pick the more tasteful one.
7. **Schedule** all of it to fire exactly on the chosen beat, and confirm to the user in DJ language ("bringing song two in on the next phrase, swapping the bass on the drop").

**The 5-step execution order** (the sequence inside a single transition, from the pros): (1) count the outgoing phrase, (2) cue the incoming at a phrase start, (3) match tempo and check for drift, (4) bring in mids and highs first with bass reduced, (5) swap bass or cut cleanly on the next phrase change.

---

## Part 7 — Mapping the product's live commands to the rules

For the continuous, prompt-driven V1, here's how each demo command resolves:

- **"layer song two on top"** → introduce Track B, tempo-match (B1/B2), snap to next phrase-start downbeat (A1), prefer B's beat-only intro (A4), enforce single bassline (D1) and single vocal (E1). Move = beat-only-intro blend or long harmonic blend by key (C1/C2).
- **"add the drums" / "drop the drums"** → un-mute/mute the drums stem on the next bar or phrase downbeat (Rule 0), 2–4 bar fade.
- **"bring the bass up" / "take the bass out"** → adjust the bass stem/low EQ, enforcing single-bassline (D1); "bring up" prefers cutting competitors (D3); "take out" = a bass-cut lift/tension depending on length (G5).
- **"add a filter sweep"** → G4: LPF/HPF over 4–16 bars, on the beat (G2).
- **"add reverb" / "add echo"** → G1/G2/G3, time-boxed to the transition, on the grid.
- **"make it darker"** → H8: ease energy down, move key toward minor (C4), optionally LPF and drop a layer.
- **"take the energy up"** → H8: BPM creep (H3), brighter key or +2 (C4), add a layer, prefer a rising build.
- **"transition into song three"** → choose the move via F1–F6 based on key/energy/BPM/section state; anchor to the next phrase (A1); execute the 5-step order (Part 6); enforce all clean-up constraints.

---

## Part 8 — Confidence, limits, and where rules break

- **High-confidence, near-universal rules:** the counting system (Part 2), phrase-start entry (A1), single-bassline (D1), single-vocal (E1), Camelot safe moves (C1), no-redline (I1). These are repeated verbatim across essentially every source and can be trusted as defaults.
- **Context-dependent rules:** transition-type choice (Part 5/6), energy arc (H), effect taste (G). These are *guidelines DJs deliberately break* for effect. Encode them as defaults the AI may override with reason, not as hard blocks.
- **Where rules break (by design):** quick cuts, breakdowns, and percussive-only mixes let you ignore key (C2); a deliberate key clash or +2 boost, kept short, creates excitement (C5); silence and bass-cuts violate "keep it full" on purpose (G5/G6). The art is knowing *when* to break a rule — which is exactly the judgment your feedback loop will later learn from real users.
- **Genre matters:** phrase length, transition length, and effect intensity all shift by genre (Part 2). Detect genre (or let the user set it) and adjust the defaults.
- **The honest gap:** these rules get you to "sounds intentional and clean" — roughly the mechanical + lower judgment layer. The last mile ("this specific transition *feels* magic") is taste. V1 approximates it with rules + the AI picking among legal options; V2+ improves it by learning from which transitions your users keep vs. redo.

**Important distinction:** Part 8 is about *rule* confidence — how universal a given DJ rule is. That is different from *data* confidence — whether the analysis feeding the rules is trustworthy on a given track. A rock-solid rule fired on a wrong beatgrid still sounds broken. Data confidence is handled next, in Part 9.

---

## Part 9 — Analysis confidence & fallback (what to do when the data is wrong)

Every rule in Parts 1–8 begins with something like "find the phrase-start downbeat," "detect the breakdown," or "read the key." Those all assume the analysis is correct. Often it won't be. **Analysis being wrong — not the rules — is the enemy.** A perfect rule fired on a bad beatgrid lands the move at exactly the wrong moment and sounds broken. This part makes the system distrust its own data and degrade gracefully.

### 9.0 The core principle
*Never fire a precise move on imprecise data.* Confidence gates the move. High confidence → do the intended, precise move. Low confidence → fall back to a move that doesn't need precise data, widen tolerances, or tell the user. It's better to do a clean, simple thing than a "correct" thing on wrong timings.

### 9.1 Confidence is per-element, not per-track
Each analyzed element carries its own confidence score (0–1). A track can have a rock-solid BPM but unreliable section labels. Track and store confidence separately for:
- **BPM** (is the tempo estimate stable?)
- **Beatgrid** (do beats stay locked across the whole track, or drift?)
- **Downbeats** (which beat is "the one"?)
- **Phrase starts** (where do 8/16-bar blocks begin?)
- **Key / Camelot** (is there a clear tonal center at all?)
- **Sections** (intro/verse/drop/breakdown labels)
- **Vocal regions** (where the lead vocal actually is)

### 9.2 What lowers confidence (flag these on ingest)
- Live or acoustic drums, loose/human timing, swing → beatgrid + downbeat confidence down.
- Tempo that drifts across the track (not a fixed BPM) → beatgrid confidence down; a single global BPM is a lie.
- Sparse/ambient intros with no clear beat → downbeat/phrase confidence down.
- Atonal, heavily percussive, or noise-based tracks → key confidence down (there may be no meaningful key).
- Irregular structure (6/10-bar phrases, odd arrangements) → phrase/section confidence down.
- Low-quality source (heavy MP3 compression, bootlegs, YouTube rips) → everything down.
- Dense mixes / lots of reverb → stem-separation and vocal-region confidence down.

### 9.3 Cross-checks that produce confidence (compute these, don't trust a single estimate)
- **Agreement check:** run two independent BPM/beat estimators. If they agree, confidence up; if they disagree, confidence down.
- **Drift check:** verify the grid still lines up with detected onsets at the *end* of the track, not just the start. Grids that drift late are the classic silent failure.
- **Onset-vs-grid check:** do the actual drum-stem onsets fall on the predicted beats? Mismatch → beatgrid confidence down.
- **Downbeat via stems:** kick/snare pattern usually reveals "the one." If the pattern is ambiguous, downbeat confidence down.
- **Key stability:** does the detected key hold across the track, or flip? Flipping → key confidence down.

### 9.4 The fallback ladder (degrade, don't fail)
When an element's confidence is too low, step *down* the ladder to the coarser thing you *can* trust:

- Can't trust **phrase starts** → anchor to **downbeats** instead (mix on any bar, not just phrase blocks). Widen the acceptable-entry window.
- Can't trust **downbeats** → anchor to **any beat**; avoid moves that need "the one" (e.g. dramatic drop alignment).
- Can't trust the **beatgrid at all** → **do not beatmatch.** Switch to timing-free moves: hard cut, echo-out, or mix through a breakdown/gap. Never attempt a long beatmatched blend on an untrusted grid.
- Can't trust the **key** → treat as "key unknown": only allow moves where key doesn't matter (quick cut, percussive blend, breakdown swap); never do a long exposed melodic/acapella blend.
- Can't trust **sections** → fall back to fixed-length assumptions (Part 2 defaults) and prefer shorter, safer moves; don't promise a "breakdown swap" you can't locate.
- Can't trust **vocal regions** → assume vocals *might* be present and protect against clash conservatively (duck one vocal stem across the whole overlap rather than relying on precise vocal timing).

### 9.5 Confidence → move-selection (which moves need which data)
Map each move to the data it depends on, and only offer it when that data clears a threshold:

| Move | Needs trusted… | If data is shaky, downgrade to… |
|---|---|---|
| Long harmonic blend | beatgrid, phrase, key | quick cut or filter sweep |
| Bass swap | beatgrid, downbeat | cut on a coarse beat, or skip the swap |
| Breakdown swap | sections | beat-only-intro blend, or cut |
| Acapella-over-instrumental | key, vocal regions, beatgrid | don't attempt |
| Phrase-aligned entry | phrase starts | downbeat entry, wider window |
| Quick cut / echo-out / loop | little (robust) | **these are the safe degraded defaults** |

**Rule of thumb:** the harder a move leans on precise structure, the higher the confidence bar to allow it. Cuts, echo-outs, and loops are the "always available" moves because they barely depend on analysis.

### 9.6 Runtime verification (trust, but verify at the moment of firing)
Even good analysis can be locally wrong. Just before a scheduled beatmatched move fires, do a fast **phase check** — confirm the two tracks' downbeats actually coincide at that point. If they don't line up within tolerance:
- nudge the alignment if the error is small, or
- abort the blend and fall back to a cut (Part 9.4).
During a long blend, keep a **drift watchdog**: if the two grids start separating audibly, correct or bail out early rather than letting it smear.

### 9.7 Communicate honestly (low confidence is a UX event, not a hidden failure)
When confidence forces a safer path, the product should quietly do the safe thing and, where useful, say so in DJ language: e.g. "that track's grid is loose — I'll cut instead of blend," or "no clear key on that one, so I'll keep the overlap short." This turns a limitation into perceived skill (a good DJ also refuses risky blends on sketchy tracks).

### 9.8 For the curated demo vs. real uploads
For the demo, you sidestep most of this by **pre-verifying** your 3–4 curated tracks offline — hand-check the beatgrid, key, and sections so confidence is effectively 100% and the safe path is never triggered on stage. But build the confidence + fallback layer anyway, because the moment V1 accepts user uploads, low-confidence tracks are the norm, not the exception, and this layer is what stops the product from embarrassing itself.

---

## Part 10 — Live command orchestration (real-time prompts: queue, override, delay, decline)

Parts 1–9 assume a planned mix. Your product is **live and reactive**: commands arrive at unpredictable moments while music is already playing, sometimes faster than they can be executed, sometimes conflicting, sometimes too late to honor cleanly. These are not DJ-craft questions — they're product-logic questions — but they matter as much as the DJ rules, because this is where a live tool feels either magical or broken.

### 10.0 The two invariants (never violate these)
1. **The music never stops.** No command may cause silence, a stall, or a stutter in the master output. If a command can't be honored, playback continues on its current path and the system reports back.
2. **Nothing fires off-grid.** Every accepted command still binds to a beat (Rule 0). "Live" does not mean "instant" — it means "on the next musically correct beat."

### 10.1 Command lifecycle
Every command moves through states:
`received → interpreted → scheduled (bound to a future anchor beat) → armed → executing → done` — or exits early as `cancelled`, `delayed`, or `declined`.

The key concept is the **pending window**: the gap between "scheduled" and "executing," i.e. now until the anchor beat. During this window the command is committed but hasn't happened yet — which is exactly where new commands can collide with it.

### 10.2 Runway: does this move have enough time?
Each move type has a **minimum runway** (bars needed to execute cleanly):
- Quick cut / layer toggle: ~1 bar (or the next bar).
- Bass swap / short blend: ~4 bars.
- Long harmonic blend: ~8–16 bars.
- Echo-out transition: ~2–8 bars.

When a command arrives, compute the runway available before the natural anchor (e.g. bars left until the current track's outro). If **runway ≥ minimum**, schedule the intended move. If **runway < minimum**, do NOT jam it in — apply the *too-late policy* (10.4).

### 10.3 Concurrency: how simultaneous/overlapping commands interact
Classify each new command against what's already pending:
- **Independent** (different subsystems, e.g. "add reverb" while a bass tweak is pending) → both proceed; **merge** them onto the same beat if they share an anchor.
- **Conflicting** (same subsystem or same transition, e.g. "take it up" then "actually make it darker") → **later overrides earlier**; cancel the superseded pending command before it fires.
- **Superseding** (a structural command that makes pending tweaks moot, e.g. "transition to song three" cancels a pending "add drums" to the *current* track) → the structural command wins; drop the now-irrelevant pending actions.
- **Duplicate / rapid-fire** (same command twice in a beat, or "add drums" when drums are already in) → **debounce / no-op**; confirm current state instead of re-firing.

### 10.4 The too-late policy (the do-or-die of a live tool)
When a command can't be honored cleanly in the available runway, pick one, in this order:
1. **Delay to the next valid anchor** — do the intended clean move, just one phrase later. Preferred when the user won't mind a short wait. (e.g. "transition now" 1 bar before a phrase end → do it at the *next* phrase.)
2. **Downgrade the move** — honor the intent immediately with a move that fits the runway (e.g. asked for a long blend with only 2 bars left → do a quick cut or echo-out instead).
3. **Decline with a reason** — only when neither a delay nor a downgrade would sound good. Say why in one line ("not enough runway for a clean blend — want me to cut, or wait for the next phrase?").

Never silently do nothing, and never force a move that will sound broken just to obey literally.

### 10.5 Priority order when commands collide
When two commands compete and can't both win, resolve by priority (high preempts low):
1. **Safety / clean-up** (enforce single bassline, single vocal, no redline) — always wins; can't be overridden into a broken state.
2. **Structural** (transitions between tracks).
3. **Energy direction** (up/darker/keep-going).
4. **Layer changes** (add/remove drums, bass, vocal).
5. **Effects** (reverb, echo, filter).

Example: if "add reverb" (5) would collide with a "transition to song three" (2) already arming, the transition proceeds and the reverb is re-evaluated against the *new* track after the switch.

### 10.6 State awareness (idempotency)
The engine tracks live state — which stems are active, current energy, current key/BPM, what's pending. Commands are interpreted against that state:
- "add drums" when drums are already in → no-op + confirm.
- "take the bass out" when it's already out → no-op + confirm.
- "make it darker" when already at floor energy → acknowledge, do nothing drastic.
This prevents the AI from stacking redundant or contradictory actions.

### 10.7 The auto-pilot fallback (because the user won't always type in time)
A real DJ keeps the floor moving even in silence between decisions. Your engine needs a default when a track is ending and **no command has arrived**:
- **Extend:** loop the current track's outro/last phrase to buy time, and surface a gentle prompt ("Track ending — say the word for song three, or I'll loop it").
- **Or auto-continue:** if configured, prepare and execute a safe default transition (the F6 safe move) to a sensible next track rather than letting the set die.
Either way, **the two invariants hold**: music keeps playing, and the move lands on the beat. Auto-pilot is what stops dead air when the user is just watching.

### 10.8 Confirmation & feedback (load-bearing for trust)
Every command gets a short, on-grid response in DJ language:
- Accepted → what and when: "bringing song two in on the next phrase, swapping the bass on the drop."
- Delayed → "queued for the next phrase (about 6 seconds)."
- Downgraded → "not enough runway for a blend — cutting on the next bar instead."
- Declined → the one-line reason + an option.
In a live tool the user is steering blind between beats; these confirmations are how they trust the wheel. This is UX, but treat it as part of the engine, not an afterthought.

### 10.9 How the three layers stack (putting it together)
On every command, the flow is:
1. **Orchestration (Part 10)** decides *whether and when* the command becomes a scheduled action — runway, concurrency, priority, too-late policy.
2. **Decision framework (Part 6)** decides *what* that action is — which move, anchor, length, bass/vocal plan, key shift, FX.
3. **Confidence & fallback (Part 9)** decides *whether the data supports that action*, and downgrades it if not — right up to a runtime phase-check the instant before it fires.
Then it's scheduled to the beat, executed, and confirmed. Orchestration wraps the decision; confidence guards the data; the DJ rules supply the taste. All three, or the wild breaks it.

---

## Sources

Synthesized from the following outlets and makers (representative pages):

- **Pioneer DJ** — genre-by-genre mixing techniques (phrasing, echo-outs, double-drops, FX by tempo): blog.pioneerdj.com
- **Mixed In Key** — the Camelot / harmonic-mixing system, safe moves, energy boosts, +7 semitone: mixedinkey.com
- **DJ TechTools** — phrasing ("respect the chorus," rule of 32), EQ theory, bass-swap: djtechtools.com
- **MusicRadar** — EQ & filter tricks, bass-cut lifts, filter sweeps: musicradar.com
- **Digital DJ Tips / DJing Tips** — ways to mix in the next track, intro-over-breakdown/outro: djingtips.com
- **Club Ready DJ School** — beginner mistakes: bass swap, phrasing, gain/redlining: clubreadydjschool.com
- **Point Blank Music School** — set structure, transitions, effects restraint, reading the room: pointblankmusicschool.com
- **DJ.Studio** — phrasing, EQ mixing, Camelot wheel, tempo-change techniques, BPM controls: dj.studio
- **Mixgraph** — transition-type catalog + selection framework, energy flow: mixgraph.io
- **SetFlow** — set energy arcs (Journey/Peak/Warm-up/Cool-down/Chill), thirds, BPM creep: setflow.app
- **Pirate / Home DJ Studio / ZIPDJ / We Are Crossfader** — EQ band ranges, gain staging, worked transition examples (Serato Stems, echo-outs, key shifts).

*This handbook is planning- and build-grade guidance distilled from DJ education and software documentation. It encodes widely-taught craft, not a proprietary model. The judgment layer built from it should be treated as tunable defaults, refined by listening and, later, by real user feedback.*
