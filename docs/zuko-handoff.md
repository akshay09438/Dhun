# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-14.** A documentation session that turned into a build session. Two beliefs the project had written into five documents were false; the Discord door now lets the first 30 people in without a form; and a read-only probe of the LIVE server proved a third document wrong. **PRs #46 and #47 are merged. One PR is open and unmerged: `fix/lobby-not-shown-to-members`.** All four suites re-run at handoff and green.

⚠️ **READ FIRST, still true: never run `/setup` on the founder's live Discord server, any flag.** It recreates its default channels beside the renamed ones. To change channel copy use `scripts/refresh_copy.py` (dry run by default).

⚠️ **GRINDER IS RUNNING, BUT AS A BACKGROUND PROCESS OF THAT SESSION** (started 2026-08-14 13:58, `Grinder#7345`, 1 server). It was started from the agent shell, **so it will die when the machine sleeps or the session ends, silently.** _This warning was made on 2026-08-13 and came true overnight — the bot was dead by morning, log frozen at 22:51._ **Keep this warning in every handoff until the bot is started from `Start-Grinder.bat` or a host.** Check `services/discord-bot/logs/run.log` for a recent line before assuming it is up.

⚠️ **A LIVE-SERVER PERMISSION CHANGE WAS APPLIED TODAY** (see "The live server" below). It is reversible in one command.

---

## THE HEADLINE: the docs were confidently wrong three times, and only running things found it

**1. A mix costs NOTHING to make.** `docs/launch-costing-200-500-users.md` claimed ~1.5¢ per mix and **$16.20/month of Claude** at 300 members. All three Claude call sites were traced: the **arrangement brain** (`plan.py:786`) is behind `USE_AI_ARRANGEMENT`, off by default and **not set in `.env`** — it has never once run, and it was ~90% of the estimate. The **mix name** is called by the **web app only**; the Discord bot defines `api_client.mix_name` and **nothing calls it**, so a `/grind` costs zero. **Live suggestions** has no UI caller at all. Baseline falls from ~$20/month to **under $1**.

**The error's shape is the lesson: the cost was read from the EXISTENCE of code that calls Claude, never from whether it RUNS.**

**2. The render waiting list was built on 2026-08-11 and five documents still called it unbuilt.** Worse than a stale date — the costing doc, the functional spec and `door-policy-design.md` all asserted that **overflow past 8 FAILS rather than queues.** The code contradicts that: waiting jobs sit in a FIFO deque and are served. **Fifty people grinding at once is 8 building and 42 waiting, and nobody's mix fails.** Refusal happens only when one person holds 3 places already or the line passes 200. `technical-spec.md` had it right the whole time, including a load test (20 fired, 20/20 succeeded, peak running 8, peak waiting 12).

The drift kept respawning from `concurrency-diagnosis.md`, whose "there is no queue at all" was true on 11 Aug and **was acted on the next day** — its own recommendation became `renderq.py`. That file now carries a HISTORICAL banner.

**3. `lock_the_door.py` HAD already been run — the live server was locked all along.** The functional spec and the plan both said "BUILT BUT NOT SWITCHED ON — the live server is untouched." **False.** A read-only probe showed a brand-new arrival sees `#the-door` and **nothing else**; `read-this-first`, `general`, `rules`, both mix rooms and the rest are all hidden from `@everyone`. **Believing the docs here would have meant running `lock_the_door.py` on an already-locked server — the exact class of action that half-locked it on 2026-08-13.**

---

## What shipped

1. **The costing document corrected — PR #46 (merged).** Rewritten with a correction notice explaining how it went wrong. Also fixed there: the queue drift across `implementation-plan.md`, `functional-spec.md`, `door-policy-design.md` and `concurrency-diagnosis.md`. Wrong claims **struck through, not deleted**, so the correction sits beside what was believed.
2. **The door opens below 30 — PR #47 (merged).** Under **30 real community members**, anybody who arrives is granted `@Member` on join, with no form. At 30 the existing door takes over unchanged. **25 new tests; suite 397→422.** No existing test modified or weakened. Design: `docs/door-open-below-30-design.md`.
3. **The lobby no longer follows people inside — `fix/lobby-not-shown-to-members`, PUSHED AND OPEN, NOT MERGED.** `#the-door` is now denied to `@Member`, so a new arrival lands on `#read-this-first`. **The live permission change is already applied** (founder's explicit yes after reading a dry run); only the script and docs are awaiting merge.

---

## The live server, as measured today (not claimed)

A read-only probe (`door_probe.py`, session scratchpad — throwaway, not committed) logged in and read the real state:

|                          |                                                                                                 |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| Discord reports          | **5 members**                                                                                   |
| `door.community_count()` | **1** (`domiitwt`)                                                                              |
| Correctly skipped        | `Grinder#7345` (bot), `Grinder#4594` (bot), `akshay5397` (owner), `bearwolf101` (Administrator) |
| `taking_all_comers()`    | **True — the door is OPEN**; a newcomer is granted `@Member` and never meets the form           |
| Bot can grant `@Member`  | **True**                                                                                        |
| A stranger sees          | `#the-door` only                                                                                |
| Somebody who is in sees  | **10 channels, `read-this-first` first, `#the-door` absent** (was 11 including the lobby)       |

**The permission change applied:** deny `view_channel` to `@Member` on `#the-door`. **Verified by the INDEPENDENT probe, not by the script that made the change.** Reversible: `python services/discord-bot/scripts/hide_door_from_members.py --undo --apply`.

Safe by construction: it never touches `@everyone` (the 2026-08-13 failure was an `@everyone` deny landing before the `@Member` grant, which locked the bot out of the channel it was editing); Administrator bypasses channel overwrites so the founder cannot lose sight of their own lobby; and `lock_the_door.py` explicitly skips `#the-door` in its `keep_open` set, so a re-run cannot silently undo it.

---

## Do first next session

**THE JOB: extract stems / BPM / key for the rest of the songs.** Founder's stated next step.

1. **Use `scripts/ingest_catalog.py`** — the existing pipeline (normalize → store → Replicate stems → analyze → manifest). It is **idempotent**, so a re-run is safe, and it should be **retried on Replicate timeouts** rather than treated as failed. Audio and the manifest stay **local-only**; only marks are code.
2. **Everything heavy goes through Replicate.** This machine is Windows-ARM and cannot run the audio models locally — do not propose a local ML library.
3. **WATCH THE DISK.** ~98 MB per mix, stems on top, and the janitor's cushion is **6 GB**. Free space today is **7.32 GB** — a bulk ingest can cross that line. Founder's standing rule: **under 2 GB, stop and ask.** Check before starting and between batches.
4. **A freshly ingested song's KEY needs an ear-check before it can key-shift.** New songs mix fine, but key-shift pairs can K1-decline as a safety measure until the detected key is confirmed by ear. Same-key pairs work immediately. Expect declines on new songs and do not read them as bugs.
5. **There is a pipeline of songs already waiting:** **149 of the 176 songs in `scripts/song_marks.csv` are not in the catalog at all.** That file is where the founder's marks live.
6. **Merge the open PR** (`fix/lobby-not-shown-to-members`) — the live change is applied but the script and docs are not saved.

---

## Findings worth keeping

- **⚠️ `scripts/song_marks.csv` IS DEAD CODE — nothing reads it.** A mark does not reach the app until it is hand-copied into `hooks.py` / `main_drops.py` / `beat_guest_verse.py` against the song's content id. **Dooriyan and How Deep Is Your Love still have marks that never landed** — Dooriyan is the one the functional spec calls "the only catalog vocal with no hand-marked hook". Still not done.
- **`store.approved_count()` is the obvious counter and the wrong one** for anything meaning "how big is the community" — it counts only form approvals, missing vouched friends, admins and every free arrival. Using it for the door would have meant **the door never closes**. `community_count()` in `door.py` is now the single definition.
- **Two bugs found by BUILDING the door, both worse than anything in its design.** (1) **The cold-cache hole:** `guild.members` is an intent-fed cache; an empty one counts zero real members, reads as "tiny community", and would hand `@Member` to every stranger arriving after a restart on a server meant to be shut. `taking_all_comers` now returns **shut** for an absent guild, an empty list, or `member_count > len(members)`. **Mutation-verified: deleting that guard turns 8 tests red, two of which predate the feature.** (2) **A cosmetic note was costing people their entry:** the closing announcement ran BEFORE the grant, so a guild whose channel lookup raised left a **vouched friend silently in the lobby**. Split into pure bookkeeping before, and send-and-swallow-everything after.
- **A dated diagnosis that gets acted on is a good outcome; one that keeps being cited is drift.** Four documents quoted an 11 Aug finding that its own recommendation had already fixed.
- **The founder's own accounts are excluded by WHAT THEY ARE, never by username** — `akshay5397` via `guild.owner_id`, `bearwolf101` via Administrator. A rename would silently break a username list.
- **Kicking `bearwolf101` to test the door would strip `@Backup Admin`** (a kick removes all roles) and prove nothing, since that account is excluded from the count either way. `akshay5397` cannot be kicked at all — Discord will not let you kick a server owner.

---

## Verification evidence — all run at handoff, 2026-08-14

| Check                                          | Result                                                                                                   |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Backend (`pytest services/api -q`)             | **823 passed** in 206s                                                                                   |
| Discord bot (`pytest services/discord-bot -q`) | **422 passed, 1 skipped** (was 397/1; +25) — pre-existing ARM `davey` skip                               |
| Web (`npm test`)                               | **78 passed** (9 files)                                                                                  |
| `npm run typecheck`                            | clean                                                                                                    |
| `npm run lint`                                 | clean                                                                                                    |
| `workers/render.py`                            | **UNTOUCHED** all session (`git diff 16d66ab HEAD`)                                                      |
| `services/api/app/planner/validate.py`         | **UNTOUCHED**                                                                                            |
| `services/api/app/storage.py`                  | **UNTOUCHED**                                                                                            |
| `services/api/app/routes/songs.py`             | **UNTOUCHED**                                                                                            |
| `.github/workflows/**`                         | **UNTOUCHED**                                                                                            |
| Mutation check (door trust guard)              | removing it turns **8 tests red**, 2 predating the feature                                               |
| Live door state                                | probe read it: `community_count()`=1, door **OPEN**                                                      |
| Live lobby change                              | applied, then **re-verified by a separate read-only probe** — `@Member` sees 10 channels, no `#the-door` |
| ASCII scan on changed files                    | clean (one `⚠️` removed from a `door.py` docstring)                                                      |
| Disk                                           | **7.32 GB free**; `%TEMP%\pytest-of-Akshay` back to **1.45 GB** after the backend run                    |
| Grinder                                        | running, logged in 13:58 — **but see the warning at the top**                                            |

Session diff: 9 files, +1244 / −125. Only `door.py`, `bot.py`, one new script, one new test file, and docs.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **One PR is open and unmerged:** `fix/lobby-not-shown-to-members`. The live server change is **already applied**; merging saves the script and the doc corrections.
- **The bot holds Administrator.** Measured 2026-08-13: it already holds everything it needs in its own right and already outranks `@Member`, so removing Administrator is safe. **Not removed** — judged cheap but not urgent.
- **`require 2FA for moderator actions` is OFF, deliberately.** A TRAP if switched on carelessly: Discord gates Manage Roles behind it, so with no 2FA on the OWNER's account the Door stops granting `@Member` **silently**.
- **An approval was once recorded but never granted the role, cause UNKNOWN.** Evidence destroyed by a log overwrite. Treat a repeat as new information.
- **132 leaked `pitch_*` directories** in `services/api/data` from `app/audio/pitch.py`'s `mkdtemp` — **unchanged from 12–13 Aug, so it is not growing, but it is still not cleaned up.**
- **The Recycle Bin holds ~3.76 GB.** Not emptied — permanent deletion is the founder's call.
- **The test suite needs ~1.5–2.5 GB of scratch per run** and regrows `%TEMP%\pytest-of-Akshay`. **Relevant to next session's bulk ingest.**
- **`bearwolf101` holds `@Backup Admin` with Administrator.** No 2FA conversation has been had with them.
- **The catalog sweep stopped at 105 of 216 pairs**, and the catalog has since grown to 33 songs.
- **95 mixes shipped with a 21–39% tempo stretch; 94 of them unheard.** Direction matters — an octave-folded slow-down can sound great where a speed-up chipmunks — so some may be fine and some not.
- **Old Town Road's analysis found only ONE vocal region** for the whole track (a degenerate blob read, same as Rapture). Its hand-marked hook carries more weight than usual.
- **NO per-person daily cap on `/grind`, by founder decision 2026-08-14.** It used to guard against a runaway bill; with the per-mix cost at zero it would only guard disk. **Do not re-offer it as-is.** It becomes a money question again only if `USE_AI_ARRANGEMENT` is ever switched on.
- **Known and accepted:** a newcomer sees `#the-door` for about one second before the role lands. Unavoidable without hiding the lobby from `@everyone`, which would make it unfindable at 30+.
- **Known and accepted (founder decision):** the door re-opens below 30, so somebody who filled the form can be waiting while a newcomer strolls in free. Not a defect.
- **Three stale branches remain unmerged and superseded:** `docs/handoff-2026-08-06`, `docs/handoff-post-merge`, `fix/application-icon`. Safe to delete. **20+ old merged branches are still on GitHub** — clutter, not risk.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **Running things beat reading them, three times in one session.** The cost doc, the queue claim and the "server was never locked" claim were all confidently written and all wrong. Each was settled in under a minute by executing something read-only.
- **The tests caught my own bug before the founder could.** The announcement-before-grant fault was found by an existing vouch test, not by review.
- **A safety guard fixed five failing tests at once.** Making "unknown counts as shut" the rule repaired four pre-existing tests that had broken, which is a strong signal it was the right rule rather than a patch.
- **The founder overruled two recommendations** (the door re-opens rather than latching; pending applicants are not auto-approved). Both are recorded **with their accepted cost**, so neither is rediscovered as a bug.
- **The founder's correction on what "30 members" counts was load-bearing** — the first draft excluded bots only, which would have shut the door at 28 real people.
- Every commit went to a branch, never to `main`.
