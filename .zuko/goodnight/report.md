# Goodnight report — 2026-08-12

_Ran overnight, unattended, on the founder's approved plan. Nothing dangerous was self-applied._

---

## The short version

**Everything you asked for is done, and the thing you didn't think was possible turned out to be
possible: Grinder can now play music out loud in your listening rooms.** It never could before, on
this laptop, ever. That cost £0 and it is proven — not "should work", but _connected to
`#Bollywood_House` and played audio_.

One thing is waiting on your desk: the disk clean-up. It touches the file that deletes finished
mixes, so it gets a proper conversation, not a tap.

---

## The headline: voice works now

Grinder has never once made a sound in a listening room on your machine. Someone could join
`Bollywood_House`, sit there, and nothing would ever happen — that is the whole listening-room
product, dead.

The reason on record was "ARM chips can't do voice". That turned out to be **too broad, and being
too broad is what kept it unsolved.** The real reason is narrower: Discord now requires one small
encryption piece, and its authors publish a build for Intel chips but not for ARM ones. That is a
missing file, not a law of physics.

Windows 11 on ARM can run ordinary Intel programs by pretending to be an Intel machine. So an
Intel Python installs the Intel build, and it runs.

**Proven end to end at 2am:** connected to `#Bollywood_House`, negotiated encryption, played three
seconds of audio, disconnected cleanly. Then the whole Grinder test suite — all 192 — run again
under the new setup, all passing.

`Start-Grinder.bat` now picks the working setup automatically, and falls back to the old one if
it is ever missing. **It cannot be worse than it was yesterday.**

> **What this does NOT fix:** one Grinder can still only be in ONE room at a time across the whole
> server. Two rooms still means one silent room. The machinery for extra Grinder identities (free
> from Discord) is built and tested — see "not done" below.

---

## What else got done

| #   | What                                                                                                  | Proof                                                                                      |
| --- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | **A failed mix now says WHICH kind of failure** — bad pair / referee rejected it / machine full / bug | 13 tests; recorded in `events.db` with the machine's free disk and memory beside every one |
| 2   | **At most 8 mixes at once, everyone else queues**                                                     | **20 fired at once → 20 finished, 0 failed**, real engine, real songs                      |
| 3   | **A full machine never blames the user** — the grind quietly goes back in the line                    | 3 tests including "the promise must not be endless"                                        |
| 4   | **The card moves** — real stages, and "6 ahead of you, about 3 min"                                   | 11 tests, including that it doesn't spam Discord                                           |
| 5   | **One person can hold at most 2 slots**                                                               | a newcomer's first grind is served while an enthusiast's ten wait                          |
| 6   | **Where the 25–30 seconds goes**                                                                      | measured on real songs, below                                                              |
| 7   | **Groundwork for several live rooms**                                                                 | 10 tests on the decisions; not connected yet, on purpose                                   |

### Where the time actually goes (4 cold renders, real catalog songs)

```
mixing it down              15.23s   59.3%
trimming to the best part    7.98s   31.1%   <-- worth a look
matching the key             1.84s    7.2%
checking it sounds right     0.40s    1.6%
studying + planning            ~0s
TOTAL                       25.68s
```

**The interesting line is the second one.** Cropping the finished mix down to its best ~3 minutes
costs _eight seconds_ — nearly a third of the wait — and it happens **after** the full mix has
already been made. If you ever want grinds to feel faster, that is where the time is, not in the
mixing. Also worth knowing: the "AI brain" that plans the arrangement is **free** — all the time
is audio work.

Every mix now records this for itself, so this stays true about real traffic instead of going
stale.

---

## Waiting for you (one thing)

**The disk clean-up** — `services/api/app/storage.py`, card `disk-sweep-floors-and-age`.

Today the app only starts tidying when the disk drops **below 2 GB**, which is already inside the
zone where mixes start failing. This raises that to 4 GB and adds a sweep of finished mixes nobody
has touched in a week.

It scored **48 out of high — "human-required"**, because it deletes people's finished mixes and
deleted is deleted. So it is **not a one-tap**; it gets a proper look with you.

**It was tested without being applied:** the existing disk-safety suite was run against the exact
staged change loaded in memory — **15 passed, identical to the current code**. A separate sandbox
run proved a 10-day-old mix goes, a 1-minute-old mix stays, and every original song, stem,
analysis and subfolder survives untouched.

**And the gate earned its keep.** The first version of that change had a real bug — it froze the
safety window at start-up so it could never be adjusted afterwards. Five tests caught it. That is
exactly the kind of thing that ships quietly when a file like this is not gated.

---

## Cut, on your instruction

**Job 6, "keep the mp3 and drop the wav" — not built.** Your call at kickoff, and I think it was
the right one: a repeat mix comes back in **0.03 seconds** because the full file is kept, and in a
busy room that instant repeat _is_ the product. The age-based sweep reclaims the same space
without spending it.

---

## Not done, and why (honest)

- **The extra-Grinder-identities pool is built and tested, but NOT connected to playback.** Your
  own implementation plan records **five separate times** a too-forgiving test fake hid a real
  Discord bug in exactly this file. Until tonight there was no way to test that path at all, so
  wiring it blind would have been the sixth. Now that voice runs, it can be done and _proven_ —
  that is the first thing worth doing next.
- **The multi-room setup still needs your clicks.** Extra Grinder identities are free, but only
  you can create them in Discord's developer portal; the bot cannot make itself a second identity.
- **The disk change has not run against your real data folder** — only temp folders. Its first
  real run is worth watching.
- **7 days (the age sweep window) is a judgement call, not a measurement.** Nothing records how
  long a mix stays popular, because nothing records playback yet.

---

## Numbers

| Check                                  | Result                                                      |
| -------------------------------------- | ----------------------------------------------------------- |
| Backend suite, full                    | **754 passed** (was 720)                                    |
| Web suite / typecheck / lint           | 78 passed / clean / clean                                   |
| Discord bot suite (ARM venv)           | **192 passed** (was 171)                                    |
| Discord bot suite (new Intel venv)     | **192 passed**                                              |
| Backend: mix + set routes              | 34 passed                                                   |
| Backend: new queue / failure / rollups | 14 + 13 + 24 passed                                         |
| **20 grinds at once, real engine**     | **20/20 succeeded, 0 failed, peak 8 rendering, 12 waiting** |
| Live voice probe                       | **connected, played audio, clean disconnect**               |
| Disk free at close                     | 8.9 GB                                                      |

**Not touched:** the mixing engine (`workers/render.py`), the quality referee
(`planner/validate.py`), and anything that changes how a mix sounds.
