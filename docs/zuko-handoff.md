# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-15, late evening. LAUNCH DAY.** Grinder opened to real strangers, three of them used it, and eight problems were found and fixed — most of them by the founder using the product, not by the suite.

**One commit is not yet merged** (`docs/handoff-2026-08-15-night`); everything else is in `main`. All four suites green.

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.**

⚠️ **THE ENGINE AND GRINDER RUN AS BACKGROUND PROCESSES OF THAT SESSION** (engine 21:00, Grinder 21:25). **They die when the machine sleeps.** `Start-Grinder.bat` restarts both. **Restarting no longer kills open grind cards** — that was fixed tonight.

---

## Real people used it today

|              |     |                                 |
| ------------ | --- | ------------------------------- |
| **akshay09** | 58  | the founder                     |
| **Aashwin**  | 2   | **new stranger**, 20:24 & 20:28 |
| **DICTATØR** | 2   | **first stranger**, 18:42       |

15 mixes through Discord today by 3 people. **Every mix today succeeded; the last real failure was 2026-08-12.**

---

## What the founder found that the tests did not — eight things

1. **Every set they built came out in the same style order, forever.** `set_index` was hard-coded 0.
2. **🔁 Again on a multi-song grind returned the byte-identical file.** Same cause; the button was decoration.
3. **Every fresh `/grind` of a pair returned the same file too.** Grinds #28/#29/#30 were one file handed out three times; the engine built it once.
4. **The lobby trapped everyone.** Not permissions — the 13 Aug lockdown left `#the-door` the only room a newcomer could see, so Discord funnelled everyone there. **Found by the founder asking "will not users land to read this first when invited?"** — a question that overturned a fix I had already called done.
5. **The vocal arrived at the very end on long beats.** The 3-minute highlight ended at the _last_ note sung and reeled back, binning everything before it. 8-minute Rapture lost 36s of 67s.
6. **"Grinder didn't respond in time."** Grind cards were not persistent views, so every restart killed the buttons — and I restarted six times.
7. **The dev dashboard could not scroll.** `min-height` where it needed `height`.
8. **The People tab listed load-test fixtures, not people.**

---

## What shipped

|                                    |                                                                                                |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| **The door removed**               | No form, no lobby, no queue. Normal open server; newcomers land on `#read-this-first`          |
| **Sets and grinds vary**           | Per-person, per-pair position counters; a fresh `/grind` and 🔁 Again advance by one mechanism |
| **Private grinds**                 | The card and the picker are ephemeral; `#best-mixes` is the only public wall                   |
| **📣 "Show this mix to everyone"** | replaces the vague "📌 Pin it"; reactions moved to the showcase post                           |
| **The grind board**                | one standing line: "N people grinding right now", or what the room made today                  |
| **The highlight keeps the vocal**  | window chosen by most singing, not by ending last. **Ear-approved before merge**               |
| **Cards survive restarts**         | persistent view, owner read from the stored row                                                |
| **Dev dashboard**                  | scrolls; People lists only nameable people, with the hidden count stated                       |

---

## Do first next session

1. **LISTEN properly.** The founder has now heard a handful and approved the crop change by ear. Nobody has sat down and judged five mixes end to end.
2. **Watch the strangers.** Two arrived unprompted today. `/#dev` → People.
3. **Fix the log pollution** — see below; it has now cost time twice in one day.
4. **First-time pairs still take 50–70s.** Pre-warming is scoped, free and deferred by founder decision.

---

## Verification evidence — run at handoff, 2026-08-15

| Check                                                                                                                            | Result                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Backend (`pytest services/api -q`)                                                                                               | **845 passed** (was 838)                                                                                               |
| Discord bot (`pytest services/discord-bot -q`)                                                                                   | **507 passed, 1 skipped** (was 451/1 at start)                                                                         |
| Web (`npm test`)                                                                                                                 | **79 passed** (was 78)                                                                                                 |
| `npm run typecheck` / `npm run lint`                                                                                             | clean                                                                                                                  |
| `workers/render.py`, `planner/validate.py`, `storage.py`, `routes/songs.py`, `config.py`, workflows, `conftest.py`, `pytest.ini` | **UNTOUCHED** vs `origin/main`                                                                                         |
| Engine                                                                                                                           | `/health` ok, **112 songs**                                                                                            |
| Dev dashboard                                                                                                                    | scrolls (720px viewport, 3795px content, reaches 3075); People = **5 named**, 24 hidden — verified in the real browser |
| Crop fix, on the real render                                                                                                     | first vocal **160s → 6s** into the highlight; swept 32 mixes: **10 improved, 22 byte-identical, 0 worse**              |
| Free disk                                                                                                                        | **8.58 GB**                                                                                                            |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ THE TEST SUITE WRITES INTO THE LIVE `logs/grinder.log`.** It cost time **twice today**: a phantom "extra voice cannot see Hollywood_Blends", and a `test_server_setup.py` traceback that had to be ruled out while verifying a real restart. **The log cannot be trusted as evidence until this is isolated.** Same family as the `events.db` pollution.
- **⚠️ `_EFFECT_POOL_ENABLED` and `USE_AI_ARRANGEMENT` are both hard-coded `False`** — code that has never run in a shipped mix.
- **⚠️ An ephemeral card vanishes on a client reload and has no shareable link.** `/mygrinds` only offers links for mixes that were shown. **There is no way to recover a private mix you did not share** — offered, not built.
- **⚠️ `rule_shuffle._resolved_set_base` recurses** and raises past ~1000 (900 fine, 1200 raises). Bot counters wrap at 512; **the WEB app's `takeNextSetIndex()` is still unbounded** — founder was told and chose to leave it.
- **⚠️ `Member.status` is useless here**; check the bot with `scripts/command_probe.py`.
- **⚠️ `set_permissions` REPLACES an overwrite.** Read `overwrites_for`, change one field, write the whole object back.
- **⚠️ A verifying probe must print the field you did NOT change, and must not be the process that made the change.** Used repeatedly today and it earned its keep every time.
- **⚠️ AFTER A PR IS MERGED, START A NEW BRANCH.** Three PRs were merged mid-session tonight; this handoff is on a fresh branch for exactly that reason.
- **Two DIFFERENT people who pick the same pair still share a file** (~1 in 3). Founder asked, was offered the fix, and **declined**: "none, it should be how it's going on." The honest cure is a 4th and 5th mixing rule.
- **The dev dashboard has NO password** and `/admin/*` answers 200 with no credentials. Fine on localhost; **the public ngrok link is deliberately OFF** and must not go on without setting `PROMPTDJ_DASHBOARD_TOKEN` first.
- **Anchor Point × Location diagnosis is UNFIXED.** Anchor Point is a vocal-rich beat (21 vocal regions, 144s of its own singing, louder than Khalid's) but is NOT on the guest-verse list, so it sings over the whole mix. Khalid got 25.5s of a 203s mix. **One line added to a hand-maintained list is the fix.**
- **The vocal has no makeup gain** (2:1 compression, 1 dB ducking). Measured: the voice band moves ±2 dB when the singer enters. Parked since 08-08; **this is the recurrence.**
- **The dashboard's failure count is still partly fiction** — 35 shown, ~17 real, none since 08-12.
- **`storage.py` / `pitch.py` disagree** about pitch-cache rebuild cost. Dangerous surface, needs founder sign-off. Untouched.
- **`OPEN_BELOW` is still 30**, deliberately — with no door it gates nothing. The founder asked for 40; that would have been a change with no effect.
- **`#the-door` / `#applications` are hidden, not deleted.** History intact.
- **Replicate credit is ZERO.**
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **The founder out-found the test suite eight times.** Every one was visible in the product and invisible in CI.
- **The most valuable thing they did was ask a question, not report a bug.** "Will not users land to read this first when invited?" forced a measurement that overturned a fix I had already reported as complete. **The failure mode to watch is reporting completeness for the half that was touched.**
- **Measuring before building changed the fix twice.** The lobby bug was not permissions; the crop bug was not singles-vs-sets (a set on Rapture lost 59s exactly like a single — the founder's sets simply used shorter beats).
- **Tests caught two of my own mistakes mid-build** — a seeding count that included the in-flight grind, and a showcase id that would have produced dead `/mygrinds` links.
- **The pre-stop gate did its job.** The People filter was built, verified live, then REVERTED rather than left red while approval was pending, and re-applied after an explicit yes.
- **Every live change was dry-run first, applied, then verified by a SEPARATE process.**
- **Every commit went to a branch, never to `main`.**
