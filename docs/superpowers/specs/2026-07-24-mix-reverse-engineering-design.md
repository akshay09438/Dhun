# Design: Learning to mix by reverse-engineering human mashups

**Date:** 2026-07-24
**Status:** Design — awaiting founder review
**Where the code lives:** `C:\DJ-AI-Experiment` (the sandbox repo, branch `sandbox`). **Nothing in this experiment touches the shipped Prompt-DJ app.**

---

## The idea in one paragraph

Give a machine three things: two songs, and a finished human-made mashup of exactly those two songs, downloaded from YouTube. The machine's job is to work backwards — to produce that same mashup from those same two songs, by any means. Along the way it records what it had to do and what it noticed. Do this across many examples and the recorded learnings become a **playbook** for mixing songs the machine has never seen.

Note what is _not_ given: which song supplied the beat and which supplied the vocal. There is no such assignment. See "Role assignment is a finding" below — it is the single most important constraint in this design.

## What this is called

Two loops stacked:

- **Inner loop** — on one pair of songs: try, score against the target, adjust, try again. This is _search_.
- **Outer loop** — across many pairs: notice what keeps working, so example #50 starts smarter than example #1. This is _learning_, and it is where the playbook comes from.

Because we hold the finished mix but **not the list of decisions that produced it**, there is nothing to teach directly — we can only score attempts after the fact. Score-after-the-fact over a sequence of decisions is the definition of **reinforcement learning**, and that is the honest name for the shape of this system. (It is structurally the same shape as AlphaGo: trial-and-error search on the inside, a thing that gets better at guiding the search on the outside.)

## The finish line

**Same mix to a listener, not the same file to a computer.**

A bit-identical copy of the YouTube file is impossible for anyone — that audio has been through the uploader's mastering and YouTube's compression, and that damage is not reversible from outside. This is a ceiling set by physics, not by effort.

What must match is everything a listener notices:

- tempo, and how it was changed from each source
- key / pitch shift, per source
- which element of which song is playing at every second — including both songs' vocals if that is what the human did
- the exact moment each element enters, and every moment it leaves
- relative loudness of each element
- where it cuts, where it drops, how the energy moves

If those match, the two mixes played back to back are indistinguishable. That is the bar. It is a hard bar, deliberately.

## Non-goals

- Not a GAN. We never synthesise audio; we cut, stretch and layer real recordings.
- Not a trained neural network as the deliverable. At 100–300 examples a network would be unreliable; readable rules will not be.
- Not shipped audio. Reference mashups are measuring tape, never ingredients — they are analysis material only, stay local, and never enter the product or get redistributed.
- Not a change to the shipped app. Findings are promoted back by hand, later, as a separate decision.

## Design principle: the experiment must not inherit our opinions

The shipped Prompt-DJ engine has opinions baked in — a fence that decides what is legal, a validator that rejects things, an arrangement rule that says vocals enter on downbeats and there are at most three placements. Those were guesses we made months ago.

If the experiment can only make moves the shipped engine allows, **it can only ever rediscover things we already believe**, and it will be structurally blind to any human move that breaks one of our rules. It would hand our own assumptions back to us as "findings."

Therefore the experiment gets its own **rule-free renderer**. No fence, no validator, no taste. It must be able to produce mixes the shipped engine would reject. The rules are the _output_ of this work, not the input.

## Role assignment is a finding, not an input

**The two source songs are handed over unlabelled and interchangeable.** Nothing tells the machine which one is "the beat song" and which is "the vocal song", because that is precisely one of the things it is supposed to discover.

The shipped app hardcodes Song 1 = beat, Song 2 = vocal. That is a product decision, and a defensible one for a two-slot uploader. It is a _catastrophic_ thing to assume here. A human mashup may use:

- either song's beat under either song's vocal
- **both** vocals, trading verses or stacked
- one song's drums with the other's bass
- one song for the first half and the other for the second
- any element of either song, at any moment

If the experiment were told the roles up front it could only ever find mashups built the one way we happen to build them, and would be structurally blind to the rest. Worse, it would return our own assumption to us dressed as a discovery — the exact failure mode this whole design exists to avoid.

Note that the "both vocals" case is not hypothetical: the founder already established by ear that for vocal-dense pairs the right move is to keep _both_ vocals and let the lyrics trade. The shipped engine cannot express that. An experiment that inherited the shipped engine's role model could never have found it.

**Concretely, this means:** every source song is split into its elements (vocals, drums, bass, other), so a triplet presents up to eight candidate element streams — four from each song. For every moment of the target, the question is not "is the vocal present" but "**which of these eight is present, and how loud**". Which song contributed what, and when, comes out as a per-triplet finding, and the distribution of those findings across many triplets is itself one of the most valuable pages of the playbook ("in N% of mashups only one vocal is used; in M% both trade").

---

## Architecture: three brains, one body

All three methods share two components, built once.

### Component 1 — The measuring tape (scorer)

Turns any mix into numbers over time, and turns two such descriptions into a single distance score.

Per moment in time, it reports:

- **for each of the eight candidate element streams** (vocals / drums / bass / other, from each of the two songs): is it sounding, and how loud
- tempo
- key
- overall energy / loudness
- section boundaries

The eight-stream breakdown is what makes the scorer role-blind. It never asks "is the vocal present"; it asks which specific element, from which specific song, is present. A mashup using both vocals scores just as legibly as one using only one.

Comparison happens on **these curves, never on raw waveforms.** Two mixes can be perceptually identical and waveform-wise completely different because of compression, mastering and phase — a raw comparison would score a good attempt as a failure.

**Key enabling move:** the reference mashup gets stem-split too, using the same splitter already used for catalogue songs. Holding the target's vocals, drums, bass and other separately turns "which element is where in theirs vs. mine" from an inference into a direct measurement.

**Consequence worth naming:** when both songs' vocals appear in a target, the target's single "vocals" stem contains _both_ of them mixed together. Telling them apart means matching that stream against both sources' vocal stems and attributing energy to each — harder than the single-vocal case, and the reason this must be designed in from the start rather than retrofitted.

This component is the single point of failure for the whole project. If the score is blurry, every method hill-climbs confidently toward garbage. It is built and validated first.

### Component 2 — The dumb hands (rule-free renderer)

Knobs in, audio out. Deliberately stupid. Parameters cover at minimum: per-source tempo ratio, per-source pitch shift, per-source time offset, which source section plays when, cut points, crossfades, and **an independent gain-over-time curve for every one of the eight element streams**.

That last point is the role-blindness requirement made concrete: because all eight streams are independently addressable, the renderer can produce both songs' vocals at once, either song's beat under either song's vocal, one song's drums with the other's bass — or any combination nobody has thought of yet. Any move a human made is _expressible_. If the renderer cannot express a move, no method can ever discover it, so the renderer's permissiveness is a hard requirement rather than a nice-to-have.

It is allowed to make illegal, ugly and wrong mixes. The score does the punishing.

**Cost note:** stem separation is the only expensive step and happens _once per song, ever_ (stems are already cached). The renderer itself is local audio maths and runs free, thousands of times over. This is what makes trial-and-error at scale affordable.

---

## The three methods

### Method 1 — The Decompiler

Measure rather than guess. Split the target into stems, then align **every target stem against every candidate source stem** — all pairings, both songs, no assumed roles — and read the numbers off directly: tempo ratio, pitch shift, timeline offset. The alignment scores themselves reveal who contributed what: if the target's vocal stem locks cleanly onto Song Two's vocal at a 4% stretch, that is the answer, discovered rather than assumed. If it locks partially onto _both_ songs' vocals at different moments, that is a both-vocals mashup, also discovered.

Then walk the timeline second by second recording which of the eight elements is present and at what level. The output is a complete recipe, derived rather than searched — including the role assignment.

- **Strength:** fast, exact, works on the first triplet with no training, and every number carries its reason — the playbook writes itself in readable form.
- **Weakness:** recovers only moves it was built to look for. An unmodelled move (filter sweep, reverse, stutter edit) is missed or misreported.
- **Bonus — the residual:** after subtracting everything we _can_ explain, the audio left over measures what we do not yet understand. It is simultaneously an honest scoreboard and a to-do list. It also immediately catches the two triplet-killers below.

**Method 1 doubles as the triplet validator.** Large unexplained residual on day one means either the human used a different version/master of the song than we hold, or they used a third ingredient that is not in our two files. Either way, exact reproduction is impossible for that triplet and we find out in minutes rather than weeks.

### Method 2 — The Guesser

Set the knobs, render, score, keep what improved, mutate, repeat — thousands of times. Black-box search. It never needs to understand anything; it only needs the score to rise.

- **Strength:** can find moves Method 1 was not built to anticipate. Discovers rather than decodes. Leaves a complete trail of what worked, which is raw playbook material.
- **Weakness:** slow; can settle confidently into a mediocre local answer; only ever as good as the score.

### Method 3 — The Apprentice

Claude never touches audio. It receives numbers: both songs' structures, the target's structure, and precisely how the last attempt differed ("the reference has Song Two's vocal from 0:31 and Song One's vocal joining at 2:04; yours only ever uses one of them; the reference is 3% faster"). Claude writes the next recipe. Render, measure, feed the difference back, loop.

Claude is told the roles are unknown and is explicitly free to assign any element of either song to any moment — including both vocals. Its priors are musical, not Prompt-DJ's.

- **Strength:** far more sample-efficient than blind search, because it brings musical priors. And it is **the only method whose learnings come out in English by construction** — it writes down what it noticed as it works, which is the requested playbook generated as a side effect rather than mined afterwards.
- **Weakness:** can plateau; can confabulate confidently; costs an API call per attempt; convergence is not guaranteed.

### Why run all three

They fail in genuinely different ways. Method 1 is blind to the unmodelled; Method 2 gets stuck and needs a perfect score; Method 3 invents things. Whatever defeats one of them is unlikely to defeat all three. Running three is cheap because they share the body — the marginal cost is three brains, not three projects.

---

## Race plan

1. Build the measuring tape. Validate it independently before anything else runs.
2. Build the rule-free renderer.
3. Run **Method 1** on the first triplet. This also validates the triplet.
4. Run **Method 2** and **Method 3** from Method 1's answer as a warm start, _plus_ a cold-start control run of each.

**On the warm start:** beginning a search at random when the tempo could simply have been measured is waste, not purity. Method 1 covers the measurable ground in minutes; Methods 2 and 3 then compete over the remaining stretch, which is where the taste decisions live anyway. The cold-start control tells us how much the warm start is actually worth.

**Everything is logged.** Every attempt, its parameters, and its score. The logs are the raw material of the playbook.

## What success looks like

- **Minimum:** on one triplet, we produce a mix that a listener would call the same mix as the reference.
- **The real prize, which arrives earlier:** an automatic scoreboard. Today every quality judgement in Prompt-DJ is made by the founder's ears, which is the bottleneck on everything. The moment the measuring tape works, "how close is this mix to what a human did with the same two songs" becomes a number — and the existing engine can be tuned and regression-checked without anyone listening.
- **The stated goal:** across many triplets, a written playbook of rules — the constants and the variables — in a form that can be promoted into the shipped planner by hand.
- **A finding we cannot get any other way:** how often real mashups actually follow the shipped app's one-beat-one-vocal model, versus using both vocals, swapped roles, or split elements. If that number is low, it is direct evidence that the shipped app's central assumption is too narrow — and no amount of listening would have quantified it.

## First run — results (2026-07-24/25, triplet-01: Tere Bina × Father Ocean)

Built in the `C:\DJ-AI-Experiment` sandbox under `experiments/revmix/`. All three
methods ran end-to-end on the first triplet. **Preliminary — the founder judges by
ear in the morning; the scores below are a guide, not a verdict.**

**The gate did its job.** The scorer was validated against nine known-answer
controls before anything depended on it, and it caught two real bugs that would
have made every method optimise toward garbage: chroma cosine similarity has a
high floor on non-negative vectors (white noise scored 82% against the real
mashup), and a whole-mix comparison is vocal-blind (deleting the entire vocal
scored 93%, beating a 2% trim). Both fixed; final scorer passes 8/8. The same
uncentred-chroma bug then surfaced a third time in the aligner and was fixed there
too.

**What was measured about the human mix (no roles assumed):**

- Father Ocean kept at its native tempo (123 BPM), untouched.
- Tere Bina slowed ~15.6% (143.5 → ~121 BPM) to meet it. A +5-semitone pitch
  reading came with low confidence and is treated as a hint, not a fact.
- Drums, bass and instrumental → Father Ocean, decisively. Vocals → **both songs**.
  The both-vocals case the shipped engine cannot express was found by measurement.

**Method scores (50% = no relationship, not "half as good"):**

| Method              | Score                       |
| ------------------- | --------------------------- |
| Guesser, cold start | 85.9%                       |
| Guesser, warm start | 83.0%                       |
| Decompiler          | 70.8%                       |
| Apprentice, warm    | 70.8% (never beat its seed) |
| Apprentice, cold    | 65.6%                       |

**The most important finding is that score and ear diverge.** A scorer-independent
diagnostic (glitch rate, dynamics, structure) shows the Decompiler's reconstruction
is choppy (284 abrupt jumps/min vs the human's 2) — its score partly reflects
fragments, not a mix. The Guessers are smooth but flat (dynamics 0.16 vs the
human's 0.46). The lowest-_scoring_ attempt (Apprentice-cold, 65.6%) is the
smoothest and most dynamic. So the highest score is unlikely to be the best sound —
a real limit of the current metric, and exactly why ear-judgement remains the
tiebreaker.

**Honest method read (pending the ear):** black-box search (Guesser) moved the
number most and cheaply (~105k attempts in 11 min, free/local). The Apprentice
under-delivered: a 24-bucket summary is too coarse for it to place edges precisely,
and it never improved on the Decompiler's seed. The Decompiler is the only method
that outputs _why_ in readable form, but its audio needs a smoothing/segmentation
pass. No method rivalled the human — expected on night one.

**Open follow-ups surfaced by the run:** give the renderer a de-glitch/segment
pass; add a dynamics term to the score so flat mixes are penalised; feed the
Apprentice a finer timeline than 24 buckets; investigate whether the Guesser's
cold-beats-warm result is a better optimum or partial score-gaming.

## Kill criteria

Stop and reconsider if:

- The measuring tape cannot reliably distinguish a good attempt from a bad one on a hand-made control pair. Nothing downstream can work.
- Method 1's residual is large on most triplets, meaning our sources rarely match what the humans actually used. That is a sourcing problem, not an algorithm problem.
- After the first triplet, no method gets meaningfully closer than a naive baseline.

## Risks

| Risk                                           | Impact                                      | Mitigation                                                                                                                         |
| ---------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Blurry score                                   | Fatal — all methods optimise toward garbage | Build and validate it first, standalone, against hand-made controls                                                                |
| Wrong source version/master used by the human  | That triplet is unusable                    | Method 1's residual detects it in minutes                                                                                          |
| Human used a third ingredient                  | That triplet is unusable                    | Same — residual detection                                                                                                          |
| Search space too large for Method 2            | Method 2 never converges                    | Measure what is measurable; reserve search for taste decisions only; warm start                                                    |
| Sourcing clean triplets is the real bottleneck | Slows the 100–300 stage                     | Prove on one first; only scale after Step 4                                                                                        |
| Both songs' vocals present in one target stem  | Attribution is ambiguous                    | Match the target vocal stream against both source vocals and attribute energy to each; designed in from the start, not retrofitted |
| Eight streams instead of two widens the search | Method 2 slows further                      | Method 1 resolves role assignment by measurement before any search begins                                                          |

## Open questions for the founder

1. Which pair to start with, and how the reference audio gets supplied (file dropped locally, or a link with explicit permission to fetch).
2. Confirmation that the code belongs in the `C:\DJ-AI-Experiment` sandbox rather than the official repo.

Drop folder for triplets: `C:\DJ-AI-Experiment\mashup-triplets\` — one folder per triplet, three unlabelled slots inside (`1-SONG-ONE`, `2-SONG-TWO`, `3-TARGET-the-human-mix`). Deliberately no beat/vocal slots, per "Role assignment is a finding".

## Escalation path (not proposed now)

A fourth method exists: make the renderer differentiable and solve for parameters by gradient descent (DDSP-style). It is far more efficient than blind search because it knows which direction to move. It is not proposed first because the founder's machine cannot run local ML training (Windows-ARM; heavy audio goes through Replicate), discrete decisions are not differentiable, and it is a large build. Revisit only if Methods 2 and 3 both stall on the same wall.
