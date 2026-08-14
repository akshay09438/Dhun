# What it costs to run Grinder for 200–500 people

_Written 2026-08-12 for the MVP launch decision. **Corrected 2026-08-14** — see the correction
notice below; the original was wrong in a way that made this look ~40x more expensive than it is.
Every number here is either measured on this machine, read out of the code, or a published price —
each line says which. Where I am estimating, it says so and gives a range rather than a number that
looks more certain than it is._

---

## ⚠️ Correction notice — 2026-08-14

**The first version of this document was wrong about the single biggest number in it, and wrong
about the biggest risk in it.** Both errors have been corrected below. What changed:

| What it said (2026-08-12)                                                   | What is actually true (verified in code 2026-08-14)                                                                                                                                        |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| "~1.5¢ per mix for Claude — two Sonnet calls per mix"                       | **Grinder makes ZERO Claude calls per mix.** The expensive one is switched off; the cheap one is never called from Discord. See "What actually costs money".                               |
| "$16.20/month of Claude at the baseline"                                    | **$0.** The baseline total falls from ~$20/month to **well under $1/month.**                                                                                                               |
| "There is no queue and no limit in the mix-making code"                     | **There is.** A bounded render queue was built on 2026-08-11 (`services/api/app/renderq.py`) and is wired into every render path. Verified live today: capacity 8, 2 per person at a time. |
| "Risk #1: a mix-making pile-up... build the waiting list (agreed next job)" | **Already built and live.** The cliff this document was most worried about is closed.                                                                                                      |
| "Risk #3: somebody scripts `/grind` in a loop — could be £100s in a day"    | **Cannot cost £100s, because there is no per-mix money cost.** A loop now costs disk and machine time, and the queue already caps how much of the machine one person can hold.             |
| "A staged disk change still unapplied on your desk (4 GB)"                  | **Applied on 2026-08-12, at a 6 GB cushion,** not 4 GB (`janitor.DEFAULT_CUSHION_GB = 6.0`).                                                                                               |

**Why it was wrong:** the per-mix cost was read from the _existence_ of the code that calls Claude,
not from whether that code actually runs. It does not. The arrangement brain sits behind an
off-by-default switch that has never been turned on, and the naming call was counted for Discord
when only the web app makes it.

---

## The one-line answer

**Between $0 and about $60 a month for a normal community, and realistically $0.**

The two things people assume are expensive — the number of members, and people _listening_ — are
free. **And it turns out making a mix is free too, because Grinder never calls a paid AI service to
make one.** Everything that costs money is a one-off you pay when _you_ add a song to the catalog.

|                           | Light                                 | **Baseline**                          | Heavy                                       |
| ------------------------- | ------------------------------------- | ------------------------------------- | ------------------------------------------- |
| What it looks like        | mostly listeners, a handful of makers | most people lurk, a core group grinds | a hyped server, most members grinding daily |
| Mixes made per month      | ~130                                  | **~1,100**                            | ~19,000                                     |
| **Free hosting (Oracle)** | **$0 / month**                        | **~$0.50 / month**                    | **~$11–31 / month**                         |
| **Paid server (~$32)**    | ~$32 / month                          | ~$32.50 / month                       | ~$43–63 / month                             |

All three assume **300 members** (the middle of your 200–500). At 500 members, multiply the mix
counts by about 1.7 — **the money barely moves, because the money was never driven by mixes.**

**The heavy column is no longer a cliff.** In the original version it was $340/month and flagged with
a warning; with the Claude cost corrected to zero, what is left is hosting and disk. The machine
limit is still real — but the queue now handles it by making people wait instead of fail.

---

## What actually costs money — and what doesn't

I read this out of the code rather than assuming it, and on 2026-08-14 I checked not just that the
code exists but that it **runs**.

### FREE, no matter how many people

|                                                               | Why                                                                                                                                                                          |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Members joining the server**                                | Discord is free. There is no per-member cost anywhere in this app.                                                                                                           |
| **Listening**                                                 | Playback replays a file that already exists on disk. No API call, no compute, no per-listener cost. **A room full of 200 listeners costs exactly the same as an empty one.** |
| **Making a mix from Discord (`/grind`)**                      | **No paid API call happens at all.** See the table below.                                                                                                                    |
| **Playing the same mix again**                                | Cached. A repeated pair returns in 3 hundredths of a second and calls nothing. _(measured)_                                                                                  |
| **`/skip`, `/stop`, `/play`, reactions, the language switch** | Local logic only.                                                                                                                                                            |
| **The second Grinder identity**                               | Extra Discord bot applications are free, and always will be.                                                                                                                 |

### The three places the code CAN call Claude — and whether they fire

This is the correction. All three exist in the code; only one of them ever runs, and not from Discord.

| The call                  | Where                                                 | Does it fire?                                                                                                                                                            | Cost                                                        |
| ------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| **The arrangement brain** | `planner/plan.py:786`                                 | **NO.** Gated behind `USE_AI_ARRANGEMENT`, which is off by default and is **not set in `.env`**. The rules engine does the arranging. This was ~90% of the old estimate. | **$0**                                                      |
| **The mix name**          | `planner/name.py` via `POST /mix/name`                | **From the WEB app only** (`App.tsx:73`). The Discord bot has the function (`api_client.mix_name`) but **nothing calls it** — verified across the whole repo.            | ~**0.1¢** per _uncached_ web mix (60 output tokens, capped) |
| **Live move suggestions** | `planner/suggest.py` via `GET /live/suggestions/{id}` | **NO.** The endpoint exists and the web client has a function for it, but no screen calls it.                                                                            | **$0**                                                      |

**So: a mix made in Discord costs nothing. A mix made on the web costs about a tenth of a cent, once.**

The naming call is cached to disk against the two song names plus the prompt
(`routes/mix.py:727-732`), so each distinct pair is paid for exactly once, ever. With a 33-song
curated catalog there are at most ~660 distinct pairs — meaning **the total lifetime naming bill for
your entire catalog is under $1**, after which it is free forever.

### COSTS MONEY ONCE, per song added to the catalog

|                                                      | Cost                           | How I know                                                                         |
| ---------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------- |
| **Splitting a song into stems** (Replicate / Demucs) | ~2–6¢ per song, **once, ever** | Published Replicate GPU pricing; matches the estimate in `cloud-and-cost-plan.md`. |
| **Analysing a song** (beat grid, key, sections)      | included in the above          | Same service, same one-time-per-song rule.                                         |

**This is already paid for your current 33 songs.** The code caches by the song's content, so a song
is processed exactly once and is then free for everyone forever _(read from `audio/stems.py`:
`cache hit — free`)_. Because V1 uses a **curated catalog and not uploads**, this cost does not grow
with users at all — only when _you_ add songs. Adding 20 more songs would cost roughly **$1**.

**This is now the only recurring cost in the whole system, and it is driven entirely by you.**

---

## The three cases, itemised

Assuming **300 members**, on **free Oracle hosting**.

### Light — mostly listeners

_Say 10% of members make anything, about one mix each per week._

|                       | Per month |
| --------------------- | --------- |
| Mixes made            | ~130      |
| Claude                | **$0**    |
| Replicate (new songs) | $0        |
| Hosting               | $0        |
| Storage               | $0        |
| **Total**             | **$0**    |

### Baseline — a normal community _(the one to plan for)_

_Say a third of members are active, about 2–3 mixes each per week._

|                              | Per month              |
| ---------------------------- | ---------------------- |
| Mixes made                   | ~1,080                 |
| Claude                       | **$0**                 |
| Replicate (adding ~10 songs) | $0.50                  |
| Hosting                      | $0                     |
| Storage                      | $0 (see the disk note) |
| **Total**                    | **≈ $0.50 / month**    |

### Heavy — a hyped server

_Say 70% of members grinding ~3 times a day._

|                                   | Per month            |
| --------------------------------- | -------------------- |
| Mixes made                        | ~19,000              |
| Claude                            | **$0**               |
| Replicate                         | ~$1                  |
| Hosting (worth paying for by now) | $32                  |
| Storage / bandwidth               | $10–30               |
| **Total**                         | **≈ $43–63 / month** |

---

## Where the ceiling actually is — and it is not money

**The machine is still the limit; it just no longer breaks.** Measured on your laptop: one mix takes
about 25–30 seconds and already saturates all ten cores; ten at once uses about 90% of the memory.

**As of 2026-08-11 there IS a queue** (`services/api/app/renderq.py`), and it is wired into both the
mix route and the set route. Verified running live on 2026-08-14:

| Setting                             | Value | What it means for a person                                                                       |
| ----------------------------------- | ----- | ------------------------------------------------------------------------------------------------ |
| Renders at once                     | **8** | The 9th person waits in line instead of the machine falling over.                                |
| Slots one person can hold           | **2** | Nobody can take the whole room; your first grind never waits behind someone's 10th.              |
| Grinds one person can have waiting  | **3** | Past that they are told plainly, rather than silently piling up.                                 |
| Retries if a render ran out of room | **3** | A render that died for lack of memory goes back in the line — the queue's fault, not the user's. |

Grinder's waiting card shows the person their place and a rough wait ("6th, about 3 minutes"), from
a rolling average of real render times. **The failure mode this document was written to warn about —
"some mixes simply fail, with the same message a genuinely unmixable pair produces" — no longer
happens.** People wait instead.

The remaining limit is honest and unchanged: **~8–10 concurrent renders is this host's ceiling**, so
in the heavy case people would be queueing a lot, and a paid box would buy real throughput. That is
now a comfort decision, not a survival one.

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

**With Claude at zero, hosting is now the largest line item in this entire document** — which means
the "launch on the free tier" recommendation is stronger than it was, not weaker.

---

## The disk, which is the real running cost

A finished mix is **~98 MB**, and the delivered clip is smaller. At the baseline rate that is about
**100 GB a month of new files** if nothing is ever deleted.

**With money removed from the picture, this is now the number one operational risk in the app.**

What exists to handle it:

- **The disk janitor** — clears old mixes when free space falls under a **6 GB cushion**
  (`janitor.DEFAULT_CUSHION_GB = 6.0`, chosen 2026-08-12; the earlier "staged 4 GB change on your
  desk" was superseded by this and **is applied**). It refuses to sweep when the pressure is not
  ours to relieve, and says so rather than deleting blindly.
- **A subfolder warning** (added 2026-08-13) — the janitor cannot delete inside subfolders by
  design, but it now reports anything over 1 GB hiding in one, so a pile like the 4.61 GB of July
  tuning renders cannot sit invisible for a month again.

⚠️ **Live reading, 2026-08-14: 5.99 GB free — already under the 6 GB cushion.** The janitor is
therefore at its sweep threshold right now, on a machine where the test suite alone reclaims and
regrows ~2.9 GB per run.

---

## What could surprise you, ranked

_Re-ranked 2026-08-14. The old #1 is built, and the old #3 cannot happen._

| #   | Risk                                    | Size                      | What to do                                                                                                                                         |
| --- | --------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Disk fills**                          | Breaks everything         | The janitor + subfolder warning are live. Watch the cushion; it is at it today.                                                                    |
| 2   | **Somebody scripts `/grind` in a loop** | Costs **disk**, not money | The queue caps them at 2 running / 3 waiting. A per-person **daily** cap still does not exist — worth ~an hour if you want the disk protected too. |
| 3   | **A long queue at peak**                | Annoying, not broken      | Nothing. It degrades to waiting, and the card tells people where they are.                                                                         |
| 4   | **Replicate**                           | Trivial                   | Only when _you_ add songs.                                                                                                                         |
| 5   | ~~Claude cost if you go viral~~         | **Removed — it is $0**    | Revisit only if `USE_AI_ARRANGEMENT` is ever switched on.                                                                                          |

**The one guard rail still missing is a per-person daily cap** — but note that its purpose has
changed. It used to be about preventing a nasty bill; it is now about preventing one person filling
your disk. Lower urgency, same fix.

---

## How confident I am, line by line

Being honest about this matters more than the totals looking tidy — and the correction above is
exactly why this table exists.

| Claim                                             | Confidence                | Basis                                                                                                          |
| ------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Listening is free; members are free               | **Certain**               | Read from the code — no per-listener or per-member call exists                                                 |
| A song is paid for once, then free forever        | **Certain**               | The cache check is explicit in `audio/stems.py`                                                                |
| **A Discord mix makes zero Claude calls**         | **Certain**               | All three call sites traced 2026-08-14: one off by flag, one with no caller in `bot.py`, one with no UI caller |
| **A web mix makes one ~0.1¢ naming call, cached** | **Certain**               | `App.tsx:73` → `POST /mix/name`; disk cache keyed on both song names + prompt; `max_tokens=60`                 |
| **The render queue exists and is wired in**       | **Certain**               | `renderq.py` imported by `routes/mix.py` and `routes/set.py`; live `GET /queue` read today                     |
| 2–6¢ per song for Replicate                       | **Rough**                 | Published GPU pricing, not your invoice. **Check your real Replicate dashboard**                               |
| ~98 MB per mix; 25–30s to make                    | **Measured**              | On this machine, from `docs/concurrency-diagnosis.md`                                                          |
| ~8–10 simultaneous is the ceiling                 | **Measured**              | Same document. The queue's cap of 8 was set from it                                                            |
| Bandwidth ~14 GB/month                            | **Estimated**             | Calculated, never measured on a live server                                                                    |
| Free Oracle hosting works, voice included         | **Researched, not tried** | `hosting-research-2026-08-12.md` — nothing has been signed up for                                              |

**The single biggest unknown is no longer a price — it is disk, and how much a real community
actually grinds.** Every column above is a guess at the second one. Once you have a hundred people
for a week, the event log already records every mix, so the real number replaces all three guesses.

---

## What I would actually do

_Updated 2026-08-14._

1. **Launch on the free hosting, and stop thinking about the bill.** At the baseline rate you are
   looking at **under a dollar a month**, and most of that is you adding songs. Money is not a
   launch consideration for this app.
2. **Before launch, spend the effort on disk, not on money.** The waiting list is done; the janitor
   change is applied. What is left is watching the cushion and, if you want it, a per-person daily
   cap so one enthusiast cannot fill the drive overnight.
3. **Look at the real number after two weeks.** The event log already has it. Then decide about a
   paid box — and buy it for reliability and queue length, which are the honest reasons, rather than
   for a bill that does not exist.
