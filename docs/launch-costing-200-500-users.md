# What it costs to run Grinder for 200–500 people

_Written 2026-08-12 for the MVP launch decision. Every number here is either measured on this
machine, read out of the code, or a published price — each line says which. Where I am estimating,
it says so and gives a range rather than a number that looks more certain than it is._

---

## The one-line answer

**Between $0 and about $35 a month for a normal community, on top of whatever you already pay.**

The two things people assume are expensive — the number of members, and people _listening_ — are
free. **The only thing that costs real money is somebody pressing `/grind`.** So the bill is driven
by how much a community _makes_, not how big it is.

|                           | Light                                 | **Baseline**                          | Heavy                                       |
| ------------------------- | ------------------------------------- | ------------------------------------- | ------------------------------------------- |
| What it looks like        | mostly listeners, a handful of makers | most people lurk, a core group grinds | a hyped server, most members grinding daily |
| Mixes made per month      | ~130                                  | **~1,100**                            | ~19,000                                     |
| **Free hosting (Oracle)** | **~$2 / month**                       | **~$20 / month**                      | **~$340 / month** ⚠️                        |
| **Paid server (~$32)**    | ~$34 / month                          | ~$52 / month                          | ~$372 / month ⚠️                            |

⚠️ The heavy column is included because you asked to see where the cliff is. **It is not a plan** —
at that volume both the money and the machine become real problems, and there is a much cheaper fix
than paying the bill. See "Where the cliff actually is" below.

All three assume **300 members** (the middle of your 200–500). At 500 members, multiply the mix
counts and the money by about 1.7.

---

## What actually costs money — and what doesn't

I read this out of the code rather than assuming it.

### FREE, no matter how many people

|                                                               | Why                                                                                                                                                                          |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Members joining the server**                                | Discord is free. There is no per-member cost anywhere in this app.                                                                                                           |
| **Listening**                                                 | Playback replays a file that already exists on disk. No API call, no compute, no per-listener cost. **A room full of 200 listeners costs exactly the same as an empty one.** |
| **Playing the same mix again**                                | Cached. A repeated pair returns in 3 hundredths of a second and calls nothing. _(measured)_                                                                                  |
| **`/skip`, `/stop`, `/play`, reactions, the language switch** | Local logic only.                                                                                                                                                            |
| **The second Grinder identity**                               | Extra Discord bot applications are free, and always will be.                                                                                                                 |

### COSTS MONEY, per mix made

|                                                                  | Cost              | How I know                                                                                                                                                                 |
| ---------------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The arrangement brain** (Claude decides where the vocal lands) | **~1.5¢ per mix** | Read from `planner/plan.py` + `planner/name.py`; two Sonnet-tier calls per mix, ~2,300 tokens in and ~760 out, at $3/$15 per million. Range 1–3¢ depending on song length. |
| **The mix name**                                                 | included above    | One short call, 60 tokens out.                                                                                                                                             |

**That is the entire per-mix cost. About 1.5 cents.** Everything else about making a mix — the
separation, the beat-matching, the key-matching, the rendering — runs on your own machine and costs
only electricity.

### COSTS MONEY ONCE, per song added to the catalog

|                                                      | Cost                           | How I know                                                                         |
| ---------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------- |
| **Splitting a song into stems** (Replicate / Demucs) | ~2–6¢ per song, **once, ever** | Published Replicate GPU pricing; matches the estimate in `cloud-and-cost-plan.md`. |
| **Analysing a song** (beat grid, key, sections)      | included in the above          | Same service, same one-time-per-song rule.                                         |

**This is already paid for your current 30 songs.** The code caches by the song's content, so a song
is processed exactly once and is then free for everyone forever _(read from `audio/stems.py`:
`cache hit — free`)_. Because V1 uses a **curated catalog and not uploads**, this cost does not grow
with users at all — only when _you_ add songs. Adding 20 more songs would cost roughly **$1**.

---

## The three cases, itemised

Assuming **300 members**, on **free Oracle hosting**.

### Light — mostly listeners

_Say 10% of members make anything, about one mix each per week._

|                                | Per month        |
| ------------------------------ | ---------------- |
| Mixes made                     | ~130             |
| Claude (the arrangement brain) | **$1.95**        |
| Replicate (new songs)          | $0               |
| Hosting                        | $0               |
| Storage                        | $0               |
| **Total**                      | **≈ $2 / month** |

### Baseline — a normal community _(the one to plan for)_

_Say a third of members are active, about 2–3 mixes each per week._

|                              | Per month              |
| ---------------------------- | ---------------------- |
| Mixes made                   | ~1,080                 |
| Claude                       | **$16.20**             |
| Replicate (adding ~10 songs) | $0.50                  |
| Hosting                      | $0                     |
| Storage                      | $0 (see the disk note) |
| **Total**                    | **≈ $17–20 / month**   |

### Heavy — a hyped server

_Say 70% of members grinding ~3 times a day._

|                                      | Per month              |
| ------------------------------------ | ---------------------- |
| Mixes made                           | ~19,000                |
| Claude                               | **$285**               |
| Replicate                            | ~$1                    |
| Hosting (must be paid at this point) | $32                    |
| Storage / bandwidth                  | $10–30                 |
| **Total**                            | **≈ $330–350 / month** |

---

## Where the cliff actually is — and it is not money

Read this before reacting to the heavy column.

**The machine breaks long before the bill does.** Measured on your laptop: one mix takes about 25–30
seconds and already saturates all ten cores; ten at once uses about 90% of the memory. **There is no
queue and no limit in the mix-making code** — every request starts immediately, so past roughly
8–10 at the same moment the machine runs out of memory and **some mixes simply fail**, with the same
message a genuinely unmixable song pair produces.

In the heavy case you would hit that constantly. The fix is **not** to pay more — it is:

1. **The waiting list** (the job you and I already agreed is next). It turns "your mix failed for no
   visible reason" into "you are 3rd in line, about 40 seconds." Costs nothing and removes the cliff.
2. **A cheap paid box** so renders are not competing with your own laptop.

**Only then does more money buy more capacity.** Spending on hosting before the waiting list exists
buys you a faster machine that still falls over the same way.

---

## Hosting: free is genuinely on the table

From the research already in `docs/hosting-research-2026-08-12.md`:

| Option                       | Cost           | Notes                                                                                                                                                                                                                           |
| ---------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Your laptop**              | £0             | Works today. But Grinder is offline whenever the laptop is shut, and mixes compete with whatever else you are doing.                                                                                                            |
| **Oracle Cloud Always Free** | **$0 / month** | Genuinely free, always-on, **and voice works there** — that was the one thing that could have killed it, and it was checked. ARM, which this app is fine with. Read that document for the three real catches before signing up. |
| **A normal x86 box**         | ~$32 / month   | Buy it for reliability, not speed — a typical $32 box has _fewer_ cores than your laptop, so per-mix speed may not improve.                                                                                                     |

**Bandwidth is not a concern.** Voice is one audio stream per room (Discord fans it out to listeners
itself), so two busy rooms for eight hours a day is roughly **14 GB a month** — against a 10 TB free
allowance. _(Calculated from Discord's Opus bitrate; not measured on a live server.)_

---

## The disk, which is the real running cost

A finished mix is **~98 MB**, and the delivered clip is smaller. At the baseline rate that is about
**100 GB a month of new files** if nothing is ever deleted.

Two things already exist to stop that being a problem:

- **The disk janitor** — clears old mixes when space runs low. It is live; its _refusal_ path has run
  for real, its _deletion_ path has never yet been needed.
- **A staged change from an earlier night**, still unapplied on your desk, that would make it start
  tidying at 4 GB free instead of waiting until 2 GB — which is already inside the zone where mixes
  begin to fail.

**Recommendation: apply that staged change before launch.** It is the difference between the disk
being a non-issue and the disk being the thing that breaks your launch night.

---

## What could surprise you, ranked

| #   | Risk                                                                                          | Size                       | What to do                                                      |
| --- | --------------------------------------------------------------------------------------------- | -------------------------- | --------------------------------------------------------------- |
| 1   | **A mix-making pile-up** — no queue, so a spike fails people's mixes instead of queueing them | Breaks the night, costs £0 | Build the waiting list (agreed next job)                        |
| 2   | **Disk fills**                                                                                | Breaks everything          | Apply the staged 4 GB change                                    |
| 3   | **Somebody scripts `/grind` in a loop**                                                       | Could be £100s in a day    | A per-person daily cap. Not built. Worth ~an hour.              |
| 4   | **Claude cost, if you go viral**                                                              | ~$285/mo at the heavy end  | Real but gradual, and visible in your dashboard before it hurts |
| 5   | **Replicate**                                                                                 | Trivial                    | Only when _you_ add songs                                       |

**Risk 3 is the only one that can produce a genuinely nasty bill from a standing start**, and it is
the cheapest to prevent. If you want one guard rail before launch, make it that one.

---

## How confident I am, line by line

Being honest about this matters more than the totals looking tidy.

| Claim                                      | Confidence                | Basis                                                                              |
| ------------------------------------------ | ------------------------- | ---------------------------------------------------------------------------------- |
| Listening is free; members are free        | **Certain**               | Read from the code — no per-listener or per-member call exists                     |
| A song is paid for once, then free forever | **Certain**               | The cache check is explicit in `audio/stems.py`                                    |
| ~1.5¢ per mix for Claude                   | **Good**                  | Token estimate from the actual payloads × published price. Real bill could be 1–3¢ |
| 2–6¢ per song for Replicate                | **Rough**                 | Published GPU pricing, not your invoice. **Check your real Replicate dashboard**   |
| ~98 MB per mix; 25–30s to make             | **Measured**              | On this machine, from `docs/concurrency-diagnosis.md`                              |
| ~8–10 simultaneous is the ceiling          | **Measured**              | Same document. Beyond that is untested — the breaking point is unknown             |
| Bandwidth ~14 GB/month                     | **Estimated**             | Calculated, never measured on a live server                                        |
| Free Oracle hosting works, voice included  | **Researched, not tried** | `hosting-research-2026-08-12.md` — nothing has been signed up for                  |

**The single biggest unknown is not a price — it is how much a real community actually grinds.**
Every column above is a guess at that. Once you have a hundred people for a week, the event log
already records every mix, so the real number replaces all three guesses.

---

## What I would actually do

1. **Launch on the free hosting.** At the baseline rate you are looking at about **$20 a month** —
   less than one dinner. Do not buy a server to find out whether people show up.
2. **Before launch, spend the effort — not the money — on three things:** the waiting list, the disk
   change already on your desk, and a per-person daily cap.
3. **Look at the real number after two weeks.** The event log already has it. Then decide about a
   paid box with evidence instead of a forecast.
