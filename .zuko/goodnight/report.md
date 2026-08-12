# Goodnight report — 2026-08-12 (night 2)

_Ran on your approved plan of eleven tasks, with eight decisions you gave at kickoff. Nothing dangerous was self-applied — and this time nothing needed to be._

---

## The short version

**Nine of eleven done. Nothing is waiting on your desk.**

Last night ended with an envelope you had to open. Tonight ends with none — not because the risky work was skipped, but because I rebuilt it so it never had to touch the file that deletes things. More on that below, because it's the bit I'm most pleased with.

Two things are parked honestly: **Windows Update's 7.81 GB needs administrator rights I don't have**, and **the song-pair sweep was still running when I wrote this**.

---

## Before anything else: I was wrong twice today, and both are now corrected

I'd rather you hear these from me than find them.

**1. I told you the launcher was fine. It wasn't, and it was the whole problem.**

This morning I "re-verified" `Start-Grinder.bat` by reading it, and told you the old warning about it was closed. Then every `/grind` said _"The application did not respond."_

The bot was never running. The launcher had a stray bracket in one line — `(best-effort)` — and Windows reads a whole section before doing any of it, so it choked, started the engine, and quit before the line that starts the bot. **The broken line was on a branch that never even runs on your machine.**

Last night's notes had said that file was "edited but never actually run". That was right. **Reading it could never have caught this. Running it caught it in ninety seconds.** Six tests now guard it.

**2. I told you a grind really takes 67 seconds, not 26. That was wrong.**

I measured it properly instead of inferring it. End to end, from the moment you ask: **25.4 seconds**, of which **25.0 is the actual mixing work**. There is no hidden overhead — the old 26-second figure was accurate all along.

The 67 seconds was real, but it was your _busy_ session — several grinds at once, the Discord file conversion afterwards, and a laptop down to 5.86 GB. Both numbers are true; they measure different situations.

**The upshot is good news:** the thing I pointed you at is still the right target. Trimming to the best part costs **8.5 seconds — a third of every wait.**

---

## What got built

|     | What                                                                                                                                 | Proof                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| 1   | **The room stops going silent.** When nothing's queued it now replays what the community has made, favouring the ones people gave 🔥 | 13 tests                                       |
| 2   | **`/skip` and `/stop`** — anyone in the room, as you chose                                                                           | tested, incl. that stop actually stays stopped |
| 3   | **Grinder records who listened and for how long** — your two blocking data gaps                                                      | tested                                         |
| 4   | **A disk cleaner that knows when NOT to delete**                                                                                     | 14 tests + proven on your real disk            |
| 5   | **Ten cards in one channel no longer shout over each other**                                                                         | 8 tests                                        |
| 6   | **The launcher bug**                                                                                                                 | reproduced, fixed, 6 guards                    |
| 7   | **Free hosting research** — and the answer is yes                                                                                    | written up                                     |
| 8   | **Test junk cleared from your database**                                                                                             | 191 rows, backup kept                          |
| 9   | **2.83 GB of temp rubbish reclaimed**                                                                                                | measured                                       |

### The station, and your rule

You asked for past mixes, best-first. I built exactly that — **but the bot still never judges a mix.** It orders by the reactions _people_ gave, and it never announces a ranking, never shows a score, never calls anything good. Silent ordering only. Your rule holds.

It also replays straight off disk, so an hour of music costs **nothing** — no new files, no Replicate credits. And when the cleaner sweeps an old mix, that mix simply drops out of rotation.

### The envelope that isn't there

You asked why the disk cleaner needed you. Fair question — and the answer was that I'd designed it badly.

`storage.py` is dangerous because it deletes people's mixes. But it already knew _how_ to clean, and it already had a "show me what you'd delete without deleting it" mode. All it was missing was **someone to ask it, regularly**.

So the cleaner is a **new, separate file** that pokes the old one on a timer. **`storage.py` was not changed by a single character** — I checked, rather than assumed. The dangerous file is exactly as it was, and you got the feature without the sticky note.

**The futility brake works, and tonight proved why it matters.** Your disk dropped 3.4 GB during our conversation and **Prompt-DJ wasn't responsible** — Windows Update was sitting on 7.81 GB. A naive cleaner told to reach 6 GB would have deleted **all 3.54 GB of your mixes and still missed**. This one checks first and refuses. Tested on your actual disk: at a deliberately impossible target it reported being 27.36 GB short and **deleted nothing**.

---

## Hosting: free is real, and ARM isn't the problem

Full write-up: [docs/hosting-research-2026-08-12.md](../../docs/hosting-research-2026-08-12.md).

The thing that could have killed it doesn't. Oracle's free machines are **ARM** — the word that broke voice on your laptop. But the missing piece **does** publish a Linux-ARM build; it's specifically _Windows_-ARM that has none. So voice would work there natively, with no emulation trick.

That narrows your old blocker for the third time: _"ARM can't do voice"_ → _"no ARM wheel"_ → **"no Windows-ARM wheel; Linux ARM is fine."**

Two catches worth knowing: Oracle **halved** its free tier in June (4 CPUs/24 GB → 2 CPUs/12 GB) with no announcement, and account creation is often refused. Storage stays at **200 GB** — twenty times your laptop's free space.

**What I could not answer:** whether 2 shared ARM cores can actually mix a song in reasonable time. So my recommendation is a **measurement, not a migration** — one free instance, one timed render, one evening. If it's fast enough, everything else is routine.

---

## Numbers

| Check                    | Result                               |
| ------------------------ | ------------------------------------ |
| Discord bot suite        | **221 passed** (was 194)             |
| Backend, full            | **767 passed, 1 failed** — see below |
| Backend, the new cleaner | 14 passed                            |
| Backend, disk safety     | 27 passed                            |
| Web / typecheck / lint   | 78 passed / clean / clean            |
| `storage.py` changed?    | **no — byte-identical**              |

**About that one failure, honestly:** an end-to-end audio test failed while the song-pair sweep was hammering the same machine. **Run on its own straight afterwards, it passed (5 passed).** So it's two heavy jobs fighting over the same laptop, not a broken change — but I'm reporting it as a failure rather than rounding it to green.

---

## Still running, and parked

- **The song-pair sweep was still going when I wrote this.** It renders every pair for real and deletes each batch before the next, so your disk went 8.3 → 6.9 → **10 GB** rather than filling up. **Its answer is not in this report** — the results file lands in `scripts/loadtest/`. Check it before believing anything about which pairs work.
- **Windows Update's 7.81 GB** — needs administrator rights. A few clicks in Disk Cleanup and you'd roughly double your free space. **This is the biggest single lever on your laptop and only you can pull it.**

---

## What only you can do

1. **Sit in a room and hear the station.** Everything about it is proven _in tests_, and tests can't hear. Your own notes record five separate times a forgiving test hid a real Discord bug in this exact area.
2. **Press `/skip` and `/stop`.** Never done by a person.
3. **Reclaim the Windows disk.**
4. **Decide on hosting** — the research is done, the decision isn't.

---

## One thing worth knowing

After clearing the test rows, your database says something surprising: **your app has never recorded a single real failure.** Not one — and your bad-pair test this morning didn't produce one either.

So all those careful "here's why it didn't work" messages have never been shown to anyone. That's either very good news about your catalog, or failures aren't being recorded properly. **Worth finding out which.**

---

**An easy way to understand this**

Nine jobs done, nothing on your desk, and I owe you two corrections — I wrongly cleared the launcher this morning when it was the actual bug, and I wrongly told you a grind takes a minute when it takes 26 seconds. Both fixed, both written down.

The best bit: you asked why the disk cleaner needed your permission. You were right to ask. I'd planned to modify the one file allowed to delete things — instead I left it completely alone and wrote a small **timer** that taps it on the shoulder every minute. Same feature, none of the danger, no envelope for you to open.

And it already earned its keep: your disk lost 3.4 GB today and **it wasn't your app** — Windows was hoarding 7.81 GB of updates. A dumber cleaner would have thrown away every mix you've made and still not fixed it. This one looks first and refuses.

Your rooms should now keep playing music by themselves. **Nobody has heard that happen yet.** Go sit in one.
