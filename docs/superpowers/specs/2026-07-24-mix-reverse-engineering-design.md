# Design: Learning to mix by reverse-engineering human mashups

**Date:** 2026-07-24
**Status:** Design — awaiting founder review
**Where the code lives:** `C:\DJ-AI-Experiment` (the sandbox repo, branch `sandbox`). **Nothing in this experiment touches the shipped Prompt-DJ app.**

---

## The idea in one paragraph

Give a machine three things: Song A (the beat), Song B (the vocal), and a finished human-made mashup of exactly those two songs, downloaded from YouTube. The machine's job is to work backwards — to produce that same mashup from those same two songs, by any means. Along the way it records what it had to do and what it noticed. Do this across many examples and the recorded learnings become a **playbook** for mixing songs the machine has never seen.

## What this is called

Two loops stacked:

- **Inner loop** — on one pair of songs: try, score against the target, adjust, try again. This is _search_.
- **Outer loop** — across many pairs: notice what keeps working, so example #50 starts smarter than example #1. This is _learning_, and it is where the playbook comes from.

Because we hold the finished mix but **not the list of decisions that produced it**, there is nothing to teach directly — we can only score attempts after the fact. Score-after-the-fact over a sequence of decisions is the definition of **reinforcement learning**, and that is the honest name for the shape of this system. (It is structurally the same shape as AlphaGo: trial-and-error search on the inside, a thing that gets better at guiding the search on the outside.)

## The finish line

**Same mix to a listener, not the same file to a computer.**

A bit-identical copy of the YouTube file is impossible for anyone — that audio has been through the uploader's mastering and YouTube's compression, and that damage is not reversible from outside. This is a ceiling set by physics, not by effort.

What must match is everything a listener notices:

- tempo, and how it was changed from the source
- key / pitch shift
- the exact moment the vocal enters, and every moment it leaves
- which piece of which song is playing at every second
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

---

## Architecture: three brains, one body

All three methods share two components, built once.

### Component 1 — The measuring tape (scorer)

Turns any mix into numbers over time, and turns two such descriptions into a single distance score.

Per moment in time, it reports:

- is a vocal sounding, and how loud
- is the beat sounding, and how loud
- tempo
- key
- overall energy / loudness
- section boundaries

Comparison happens on **these curves, never on raw waveforms.** Two mixes can be perceptually identical and waveform-wise completely different because of compression, mastering and phase — a raw comparison would score a good attempt as a failure.

**Key enabling move:** the reference mashup gets stem-split too, using the same splitter already used for catalogue songs. Holding the reference's vocal and beat separately turns "where is the vocal in theirs vs. mine" from an inference into a direct measurement.

This component is the single point of failure for the whole project. If the score is blurry, every method hill-climbs confidently toward garbage. It is built and validated first.

### Component 2 — The dumb hands (rule-free renderer)

Knobs in, audio out. Deliberately stupid. Parameters cover at minimum: tempo ratio, pitch shift, per-source time offset, which source section plays when, per-element gain over time, cut points, crossfades.

It is allowed to make illegal, ugly and wrong mixes. The score does the punishing.

**Cost note:** stem separation is the only expensive step and happens _once per song, ever_ (stems are already cached). The renderer itself is local audio maths and runs free, thousands of times over. This is what makes trial-and-error at scale affordable.

---

## The three methods

### Method 1 — The Decompiler

Measure rather than guess. Split the target into stems, align each against the corresponding source, and read the numbers off directly: tempo ratio, pitch shift, timeline offset. Then walk the timeline second by second recording which element is present and at what level. The output is a complete recipe, derived rather than searched.

- **Strength:** fast, exact, works on the first triplet with no training, and every number carries its reason — the playbook writes itself in readable form.
- **Weakness:** recovers only moves it was built to look for. An unmodelled move (filter sweep, reverse, stutter edit) is missed or misreported.
- **Bonus — the residual:** after subtracting everything we _can_ explain, the audio left over measures what we do not yet understand. It is simultaneously an honest scoreboard and a to-do list. It also immediately catches the two triplet-killers below.

**Method 1 doubles as the triplet validator.** Large unexplained residual on day one means either the human used a different version/master of the song than we hold, or they used a third ingredient that is not in our two files. Either way, exact reproduction is impossible for that triplet and we find out in minutes rather than weeks.

### Method 2 — The Guesser

Set the knobs, render, score, keep what improved, mutate, repeat — thousands of times. Black-box search. It never needs to understand anything; it only needs the score to rise.

- **Strength:** can find moves Method 1 was not built to anticipate. Discovers rather than decodes. Leaves a complete trail of what worked, which is raw playbook material.
- **Weakness:** slow; can settle confidently into a mediocre local answer; only ever as good as the score.

### Method 3 — The Apprentice

Claude never touches audio. It receives numbers: Song A's structure, Song B's structure, the target's structure, and precisely how the last attempt differed ("your vocal entered 4 bars late; the reference runs beat-only for 16 bars first; the reference is 3% faster"). Claude writes the next recipe. Render, measure, feed the difference back, loop.

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

## Kill criteria

Stop and reconsider if:

- The measuring tape cannot reliably distinguish a good attempt from a bad one on a hand-made control pair. Nothing downstream can work.
- Method 1's residual is large on most triplets, meaning our sources rarely match what the humans actually used. That is a sourcing problem, not an algorithm problem.
- After the first triplet, no method gets meaningfully closer than a naive baseline.

## Risks

| Risk                                           | Impact                                      | Mitigation                                                                      |
| ---------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------- |
| Blurry score                                   | Fatal — all methods optimise toward garbage | Build and validate it first, standalone, against hand-made controls             |
| Wrong source version/master used by the human  | That triplet is unusable                    | Method 1's residual detects it in minutes                                       |
| Human used a third ingredient                  | That triplet is unusable                    | Same — residual detection                                                       |
| Search space too large for Method 2            | Method 2 never converges                    | Measure what is measurable; reserve search for taste decisions only; warm start |
| Sourcing clean triplets is the real bottleneck | Slows the 100–300 stage                     | Prove on one first; only scale after Step 4                                     |

## Open questions for the founder

1. Which pair to start with, and how the reference audio gets supplied (file dropped locally, or a link with explicit permission to fetch).
2. Confirmation that the code belongs in the `C:\DJ-AI-Experiment` sandbox rather than the official repo.

## Escalation path (not proposed now)

A fourth method exists: make the renderer differentiable and solve for parameters by gradient descent (DDSP-style). It is far more efficient than blind search because it knows which direction to move. It is not proposed first because the founder's machine cannot run local ML training (Windows-ARM; heavy audio goes through Replicate), discrete decisions are not differentiable, and it is a large build. Revisit only if Methods 2 and 3 both stall on the same wall.
