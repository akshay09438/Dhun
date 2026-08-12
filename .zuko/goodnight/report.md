# Morning report — the hygiene batch, the Panda question, and your costing

_Overnight run of 2026-08-12, after you confirmed two rooms playing at once. Branch
`feat/second-grinder-voice`. Nothing merged to `main`. Nothing staged for your approval — this batch
touched none of the handle-with-care files._

---

## First, the thing that matters

**Two rooms play at the same time, you heard it, and nothing starts on its own any more.** That is
the wall that was structurally impossible this morning, broken and confirmed by your own ears. The
rest of this is tidying up around it.

---

## 1. Your question: do both bots follow the same rules?

**Yes — and not because the second one was written carefully. Because it has no rules in it.**

I grepped every single thing the extra identity is ever asked to do. The complete list is four calls:
look up its own copy of a room, clear its voice state at startup, read its own user to set its
picture, and store its login. **There is no fifth.**

It cannot post, so it cannot judge a mix. It cannot render, so it cannot bypass the quality referee.
It cannot pick songs, plan an arrangement, or read a command. It is handed a finished file and plays
it.

Written up with the evidence in **`docs/second-voice-hygiene-audit.md`**, including the one-line grep
so you can re-run it yourself any time.

## 2. Your question: why wasn't Panda sung?

**It is not the arrangement's fault — and I can prove that much.**

The plan puts Panda's vocal into the mix three times. Two of those land fully inside the clip you
actually heard: **87 seconds of Panda in a 220-second clip, 40% of it.** For contrast, Father Ocean's
own vocal appears for 6.3 seconds. So the mix didn't forget him and the crop didn't skip him.

The engine also flagged that pair as awkward at the time, in its own words: _122 BPM beat against a
72 BPM vocal — about twice apart._ Panda was squeezed to 85% of his length and pitched down a
semitone. That is right on the recorded warble threshold.

**What I could not finish:** proving whether the vocal actually survived into the finished audio. Two
suspects with opposite fixes — either it's there and buried (a known, parked issue where vocals sit
6–8 dB under the beat on _every_ mix), or it never made it into the render. The measurement that
tells them apart needs the mix file, and **it was deleted off the disk by tonight's catalog sweep**
before I got to it.

That costs almost nothing to recover: a mix's id is a hash of its inputs, so re-running that pair
regenerates a byte-identical file. **Re-render, run the probe, get a verdict — about a minute.**

**I did not touch the vocal chain.** A loudness fix applied to a render bug changes nothing, and that
file is handle-with-care.

One thing worth your seeing: my _first_ attempt at that measurement gave an answer that looked
convincing and was wrong — the arrangement's own energy arc swamped it. It's written up as a
discarded method, not dressed up as a finding.

## 3. Your ask: make every song play

The never-decline rule already means no pair is refused for tempo or key. The only thing that can
still stop a mix is the referee catching a render that genuinely sounds bad — **and I didn't disable
that**, because it's the guard that stops the app quietly shipping mush.

Instead I swept the catalog for real and, for the first time, **recorded WHY each failure failed.**
The engine's own log already knew; nothing was reading it.

**Result so far (77 pairs, sweep still running):**

|                                         |                    |
| --------------------------------------- | ------------------ |
| Failed                                  | 10 of 77 — **13%** |
| ...of which the machine was simply full | 4                  |
| **Genuine pair failures**               | **6 of 77 — 7.8%** |

**That 29.6% figure you were told before was wrong**, exactly as suspected — it counted a starved
machine as broken songs. The real number is under 8%, and the offenders are specific: **Khuda Jaane
fails 2 of 4 tries** (the known one), while Father Ocean fails 3 of 24 and I Adore You 1 of 20 —
which is noise, not a broken song.

The sweep was still running when I wrote this. **`scripts/loadtest/sweep_report.py` reads the answer
straight out of the engine's log**, so it doesn't matter whether the sweep finishes cleanly — the
result is recoverable either way. That is new, and it's why last time's numbers had to be
reconstructed by hand.

## 4. Your ask: an accurate cost to launch for 200–500 people

**`docs/launch-costing-200-500-users.md`** — all three usage cases side by side, as you asked.

**The short version: about $20 a month for a normal community.**

The two things everyone assumes are expensive are free. **Members are free. Listening is free** — a
room with 200 people in it costs exactly the same as an empty one, because playback replays a file
that already exists. A song is paid for **once, ever** (~2–6¢) and is then free forever.

**The only thing that costs money is somebody pressing `/grind`: about 1.5 cents.**

|                      | Light | **Baseline** | Heavy   |
| -------------------- | ----- | ------------ | ------- |
| Mixes per month      | ~130  | **~1,100**   | ~19,000 |
| Cost on free hosting | ~$2   | **~$20**     | ~$340   |

**And the most important line in the document: the cliff is the machine, not the money.** There is no
queue in the mix-making code — past about 8–10 at once it runs out of memory and _fails_ people's
mixes instead of making them wait. Buying a server before building the waiting list gets you a faster
machine that falls over the same way.

Every claim is marked with how confident I am and where the number came from.

## 5. Fixed on the way

**No more ghost bots.** Tonight's lost hour was an invisible Grinder from 18:34 still running behind
a closed window. `Start-Grinder.bat` now clears the shift before starting. Four tests, one of which
fails if that guard is ever moved to the wrong place.

---

## Where I was wrong tonight

Twice, and both times I sounded more certain than the evidence justified.

1. **I told you the auto-play was still happening because you hadn't restarted.** You had. The real
   cause was the ghost bot, and I only found it by listing the processes on your machine — which I
   should have done first, since I can.
2. **I blamed the timeouts on you clicking inside the console window.** Plausible, well-known, and
   wrong. Same ghost bot. That one sent you chasing something that didn't matter.

The lesson recorded in the handoff: when it's your machine, look at your machine before theorising.

---

## Do first when you're back

1. **Re-render Father Ocean × Panda and run the probe.** One minute, and it decides whether the vocal
   fix is a loudness change or a bug hunt.
2. **Open and merge the PR.**
3. **Build the render waiting list.** It's the next agreed job, and the costing makes the case: it
   removes the only cliff that actually breaks a launch night, and it costs nothing to run.
4. **The disk-cleanup card** from an earlier night is _still_ sitting unapplied on your desk.

## Verification

| Check                                                                        | Result                                                |
| ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| Discord bot suite                                                            | **307 passed** (245 at session start)                 |
| Backend / web / typecheck / lint                                             | **768 / 78 / clean / clean**                          |
| `render.py`, `validate.py`, `storage.py`                                     | **untouched**                                         |
| Three mutation checks (shared connection, `.env` overwrite, cross-room read) | each re-broken on purpose, each caught, each reverted |
| Two rooms with sound at once                                                 | **confirmed by you, by ear**                          |
