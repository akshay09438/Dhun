# Can many people use Grinder at once? — a measured diagnosis

_2026-08-11. Read-only investigation: every number below was measured on the founder's machine
against the real engine and the real catalog. Nothing in the engine was changed. Test scripts are
in the session scratchpad; the method is described here so any of it can be re-run._

---

## The one-paragraph answer

**"The engine makes one mix at a time" is false.** There is no queue in the render code at all, and
measured on ten real pairs the engine runs about **5.5x parallel** — ten people who would have
waited 288 seconds one-at-a-time all finished in **52 seconds**. Ten people in ten rooms is under a
minute, not ten to fifteen. **The real ten-to-fifteen-minute problem is voice playback**, which is
genuinely one-at-a-time for a whole Discord server, and no amount of CPU fixes it. And the biggest
problem is neither: **the engine reports every failure with the same sentence**, so a starved machine and a genuinely
bad pair look identical - which sent this very investigation down the wrong path for hours.

---

## The machine everything was measured on

| | |
|---|---|
| CPU | Snapdragon X, **10 logical cores** (Windows ARM64) |
| RAM | 16.8 GB |
| Engine | one uvicorn process, one worker |
| Catalog | 12 beats x 18 vocals = **216 pairs** |

---

## What was tested, and what each test settled

### 1. What does one mix cost?

Rendered alone, nothing else running.

| | |
|---|---|
| Cold render | **22.6s / 28.3s** on first measurement; re-measured pairs ran **11.8s – 30.1s** |
| Repeat of the same pair | **0.03 seconds** |
| CPU during ONE render | peak **100%**, all **10 of 10** cores over 50% busy |
| RAM for ONE render | **1.26 GB** |

**The earlier "80 seconds" figure is wrong** — the true median is nearer **25–30 seconds**.

**The "instant repeat" claim is true.** A cached mix returns in 3 hundredths of a second.

**The important line is the CPU one.** A *single* render already saturates all ten cores. That
predicts what the concurrency tests then confirmed: extra simultaneous users are not free, they
share a machine that one user already fills.

### 2. Does it actually run mixes in parallel?

This took four attempts, because the first three disagreed wildly — 41s, 139s and 289s worst-case
for ten at once. **The cause was my test, not the engine:** render cost is dominated by the beat
song's LENGTH, and each run happened to use different songs. Innerbloom is 9:38 and costs roughly
seven times what Father Ocean does, so those runs measured the songs, not the concurrency.

The controlled version fired **the same ten pairs** twice — once one at a time, once together.

| | |
|---|---|
| One at a time (sum of each pair's solo cost) | **~288s** |
| The same ten fired together | **52.4s** wall clock |
| **Speedup** | **~5.5x** (1.0 would be fully serial) |
| Failures | **0 of 10** |
| Slowest person waited | 52.4s (fastest 27.7s — **1.9x unfairness**) |
| Throughput | **11.5 mixes/minute**, vs ~2/minute one at a time |
| RAM at 10 concurrent | **5.15 GB**; engine threads peaked at **59** |

_Honesty note: an earlier draft of this reported 8.7x. Two pairs in the one-at-a-time phase
recorded 110s+, and re-measuring them three times each gave 25–30s — those two readings were
anomalies. 5.5x is the corrected, conservative figure._

**Verdict: the engine is already close to as parallel as a ten-core machine allows.** Whoever said
one-at-a-time was reading the architecture, not measuring it.

### 3. How does it hold up as the number climbs?

| At once | Worst wait | Throughput | Engine RAM |
|---|---|---|---|
| 1 | 28s | 2.7/min | 1.26 GB |
| 2 | 31s | 3.9/min | 2.22 GB |
| 5 | 45s | 6.7/min | 3.88 GB |
| 10 | 52s | 11.5/min | 5.15 GB |

It degrades **gracefully** up to ten — waits roughly double while throughput quadruples.

**But there is no brake.** Reading `services/api/app/routes/mix.py`, every request calls
`threading.Thread(...).start()` immediately. There is **no semaphore, no worker pool, no queue and
no limit anywhere in the render path.** Fifty simultaneous requests would start fifty renders.

That matters because of memory, not speed: **during the catalog sweep the machine sat at 89.5%
memory with 1.8 GB free.** Ten concurrent renders is already most of this machine. The failure mode
past that is not "people wait" — it is the engine running out of memory and dropping *everyone's*
work, including the people who were nearly finished.

### 4. The failure nobody had measured

One mix failed during the very first ten-at-once test. Run alone, that pair failed **3 times out of
3** in 7.6 seconds — so it was never about load. Captured from the engine's own log:

```
workers.render.RenderError: vocal chain collapsed the crest factor 10.76 -> 5.33
(< 0.60x, distortion/mush) - the master would faithfully normalize the mush
```

Preceded by two warnings on the same mix:

```
half_time_pair : 122 BPM beat vs 80 BPM vocal (~2x apart)
forced_tempo   : Song 2 was stretched ~24% to lock onto Song 1's beat
```

**This is the quality guard doing its job.** Father Ocean (122 BPM) and Khuda Jaane (80 BPM) are a
half-time pair; the never-decline rule forces a 24% stretch onto the vocal, the vocal chain then
squashes the life out of it, and the referee refuses to ship mush. That is the correct call — the
project's own rule is that quietly shipping bad-sounding mixes is the worst possible outcome.

**But the user just sees "Couldn't build this mix."** They picked two songs from a menu and hit a
dead end, with no hint that a different pairing would work.

So the whole catalog was swept — all 216 pairs rendered for real, ten at a time:

> **82 of the 216 pairs were rendered before the disk ran low and the sweep was stopped.
> 17 of those 82 FAILED — 20.7%, about one in five.**

### CORRECTION — most of those failures were the MACHINE, not the songs

An earlier draft of this document blamed Innerbloom, Rapture and Khuda Jaane and recommended
withdrawing all three. **Re-testing proved that wrong for two of them**, and the correction matters
more than the original finding:

| Pair | Re-tested | Result |
|---|---|---|
| Innerbloom x Dooriyan | 6 attempts | **6/6 worked** |
| Rapture x Panda | 6 attempts | **6/6 worked** |
| Rapture x Uff Teri Ada | 6 attempts | **6/6 worked** |
| Innerbloom x 10 different vocals, all at once | 10 attempts | **10/10 worked** |
| **Father Ocean x Khuda Jaane** | 6 attempts | **0/6 — fails every single time** |

The only thing that differed between the sweep and the re-test was **headroom**: the sweep ran while
the machine was at 89.5% memory with the disk falling toward 2 GB; the re-test ran with 6.3 GB of
disk and 6.7 GB of RAM free. Same songs, same ten-at-once, opposite outcome.

**So the honest split is:**

* **Khuda Jaane is a genuine, reproducible pair failure** (see the crest-factor error below).
* **The Innerbloom and Rapture failures were not reproducible** and are best explained by the
  machine running out of room during the sweep.
* **The true per-pair failure rate of the catalog is therefore UNKNOWN**, and the 20.7% figure is
  an upper bound measured on a starved machine. It should be re-measured with headroom, deleting
  each render as soon as its result is known.

**The defect this exposes is worse than either.** `_run_mix` catches every exception and reports
them all with one sentence — *"Couldn't build this mix. Try another pair or regenerate."* A genuine
quality rejection and a machine-out-of-resources failure are **indistinguishable**, both to the user
and in `events.db`. That is why a resource problem looked like a catalog problem for several hours,
and it is why the ops dashboard's "degraded song" lists cannot currently be trusted either.

### The raw sweep numbers (upper bound, machine under pressure)

Recorded for completeness. Given the correction above, read the Innerbloom and Rapture rows as
"failed while the machine was starved", not "these songs are broken":

| Beat | Failed | Rate |
|---|---|---|
| Innerbloom (RUFUS DU SOL) | 8 of 17 | **47%** |
| Rapture (Black Coffee) | 7 of 18 | **38%** |
| Father Ocean | 1 of 18 | 5% |
| I Adore You | 1 of 18 | 5% |

| Vocal | Failed | Rate |
|---|---|---|
| **Khuda Jaane** | 4 of 4 | **100% — fails with every beat tried** |
| Dooriyan | 2 of 4 | 50% |
| eleven others | 1 each | 20–33% |

**Khuda Jaane is the one that stands up to re-testing** — 4 of 4 in the sweep, 0 of 6 on re-test,
never successful with any beat. The Innerbloom and Rapture rows did not reproduce.

**Honest limits of this number.** Only 4 of the 12 beats were reached — Anchor Point, Merrygo, Wake
Me Up, Faded, Lean On, Closer, Hey Brother and Silence are **untested**. The sweep also lost its own
summary file when it was stopped; the numbers above were reconstructed from the engine's
`events.db`, which records every render outcome and is the more trustworthy source anyway. Re-running
the remaining 134 pairs needs about 16 GB of free disk, or a change to delete each render as soon as
its result is known.

This is invisible to the existing `scripts/sanity_check.py`, which sweeps at PLAN level and reports
zero declines. These failures happen later, inside `render_mix`, when the guard measures the
finished audio. A plan-level sweep cannot see them.

### 5. Voice: the bottleneck that is real

This one is not a performance problem and cannot be bought away with a bigger server.

**A Discord bot holds exactly ONE voice connection per server** — not per room. The code already
knows this; `services/discord-bot/booth.py` keeps a single `now_playing` and a queue behind an
`asyncio.Lock`, with the comment: *"A bot can hold only ONE voice connection per server, so while
this is playing, a grind finishing in a different room waits its turn."*

Playback length, measured across 40 real finished mixes:

| | |
|---|---|
| Shortest | 162s |
| **Median** | **189s (3 min 9 s)** |
| Longest | 265s |

At 189 seconds each, through one connection:

| Grinds queued | The last one starts | and ends |
|---|---|---|
| 2 | 3 min | 6 min |
| 5 | 13 min | 16 min |
| **10** | **28 min** | **31 min** |

**This is the ten-to-fifteen-minute problem, correctly located.** It was blamed on rendering. It is
voice. Ten people in Bollywood_House and Hollywood_Blends do not wait for each other's *renders* —
they wait for each other's *playback*, and they wait far longer than anyone said.

### 6. Does the Discord bot add its own queue?

**No.** Each `/grind` runs as its own coroutine and calls the engine over HTTP; there is no lock or
pool on the bot's render path. The bot's only queue is the voice one above.

---

## What is actually breaking, ranked

| # | Problem | Real? | Fixed by money? |
|---|---|---|---|
| 1 | **Every failure reports the same sentence**, so a bad pair and a starved machine are indistinguishable | **Yes — it misled this very investigation** | No |
| 2 | **No admission control**, so a starved machine fails renders instead of queueing them | **Yes — demonstrated** | Partly |
| 3 | **One voice stream per server** — 10 rooms, 9 silent | **Yes, structural** | No |
| 4 | **Khuda Jaane cannot be mixed with anything** (80 BPM vs 120-122) | **Yes, reproducible 0/6** | No |
| 5 | **No queue position shown** — "grinding…" whether it is 30s or 5 min away | Yes | No |
| 6 | Rendering speed | **No. Already ~5.5x parallel** | n/a |

---

## What to do to reach 500 members

Ordered by how much user pain each removes per unit of work.

**1. Say WHY a mix failed, in the log and in the ops data.** One sentence covers every cause today,
which is precisely why a starved machine looked like a broken catalog for hours. Until a quality
rejection can be told apart from an out-of-resources failure, no failure number from this app can be
trusted — including the ops dashboard's existing "degraded song" lists. Cheapest fix here, and it
unblocks measuring everything else.

**2. Put a limit on simultaneous renders.** Not to make it faster — to stop it falling over. A
semaphore of about 6–8 on this machine turns a spike from "some people's mixes fail for no visible
reason" into "everyone waits a bit." The re-test showed this is not theoretical: the same ten pairs
that failed on a starved machine all succeeded when it had headroom.

**3. Fix or withdraw Khuda Jaane, and re-measure the rest.** It is 80 BPM against a 120-122 BPM
catalog, forced into a ~24% stretch, and the vocal chain then collapses it into mush. It has never
succeeded. Do NOT withdraw Innerbloom or Rapture — they were exonerated on re-test. Re-run the full
sweep on a machine with headroom before believing any catalog failure rate.

**4. Show queue position.** Ten people staring at "grinding…" with no idea whether it is 30 seconds
or five minutes will hit the button again, which genuinely does make it worse. Showing "3rd in
line" costs nothing and removes most of the felt pain.

**5. Keep two or three listening rooms, not ten.** With one voice connection per server, ten rooms
guarantees nine silent ones. Two or three busy rooms is a better night out and needs no new work.
Only if a second room is genuinely full at the same time as the first does the multi-bot setup
(a separate Discord application per room) become worth its complexity.

**6. Move to a normal x86 server (~$32/month).** Two wins in one: voice playback starts working at
all (it cannot on this ARM laptop), and renders stop competing with the founder's own machine. Note
the honest caveat — a typical $32 box has **fewer** cores than this laptop's ten, so per-mix speed
may not improve. Buy it for voice and reliability, not for speed.

**7. Automatic deletion of old mixes.** A precondition, not an optimisation. Each finished mix is
~98 MB, `services/api/data` is already 12 GB, and this machine had 4.6 GB free during testing.

**Explicitly NOT worth doing:** buying a 16-core box to make rendering faster. Rendering is not the
bottleneck, and the measurements say the money should go to voice and to the failure rate instead.

---

## What was NOT tested, and should be before launch

- **More than 10 at once.** Memory headroom ran out on this machine before the test could. The
  breaking point is therefore unknown — only that 10 is already 89.5% of RAM.
- **A sustained arrival rate**, as opposed to one big simultaneous burst. Real users trickle.
- **Voice under real load**, which cannot be tested here at all — voice does not work on this
  machine (Windows ARM64; see the technical spec).
- **Which resource actually causes the load failures.** Disk and memory were both low during the
  sweep and both healthy on the re-test; they were not isolated from each other.
- **The true catalog failure rate**, which needs a re-run with headroom. The 20.7% figure is an
  upper bound measured on a starved machine, not a property of the catalog.
