# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-15 (session closed just after midnight).** The longest session so far. The catalog went **33 → 112 songs**, the founder's marking sheet reached the app for the first time (**40 of 410 marks were wired; now 267**), the Discord server was made fit for real strangers, and a full hygiene audit ran clean.

**Everything is merged. PRs #52, #54 and #55 are all in `main`; `git log origin/main..HEAD` is empty.** All four suites green at handoff.

⚠️ **STILL TRUE, KEEP REPEATING: never run `/setup` on the founder's live Discord server, any flag.** It recreates its default channels beside the renamed ones. Use `scripts/refresh_copy.py` (dry run by default).

⚠️ **GRINDER IS RUNNING AS A BACKGROUND PROCESS OF THIS SESSION** (started 2026-08-14 23:59, `Grinder#7345`, 1 server, Intel venv so voice works). **It may die when the machine sleeps.** It now writes `services/discord-bot/logs/grinder.log` itself — **read that for a recent line before assuming it is up. Do NOT use `Member.status`; see the traps below.**

---

## THE ONE THING NOBODY HAS DONE: LISTENED

**227 newly-wired marks, a rebuilt menu, five rounds of founder swaps — and not one mix has been heard since any of it.** The mixes _should_ be better; that is entirely unverified. Everything else in this file is evidence. This is the gap, and it is the first job next session.

---

## THE HEADLINE: the founder found four things no test did

Every one was obvious in the product and invisible in the suite.

**1. 103 songs were loaded, paid for, and INVISIBLE.** After the big ingest the picker still offered the same **four** English vocals as before. `bot.py::_vocals_for` filters vocals by `language` and defaults to english; the loader never wrote that field. Nothing errored, the manifest looked right, the songs really were there. **English vocals visible: 4 → 59.**

**The check I skipped is the lesson.** Before spending Replicate credit on 103 songs I checked disk, cost, duplicates, marks coverage and analysis quality. **I never checked how a person actually PICKS a song.** One look at `select_option_specs` — `list(songs)[:25]` — would have shown a Discord dropdown holds 25 options, and the picker would have been fixed _before_ the songs were loaded into it.

**2. Locking three channels HID them instead of muting them.** `set_permissions(role, send_messages=False)` **replaces** an overwrite rather than editing it, destroying the `read_messages=True` grant those channels relied on. **And my verification could not see it** — the probe printed only `send_messages`, so it confirmed what worked and was blind to what broke.

**3. "Add another pair" hung.** Not a bug: a `/grind` card lives in the bot's memory and `GrindBuilderView` is not persistent, so **each of my six restarts killed every open card.** Measured: the button does 0.2 ms of work against a 3000 ms budget.

**4. "I don't see anything to merge" — twice.** After a PR is merged, that branch can never host another; further commits are pushed but invisible. I did it after #52 and again after #54. **Rule now recorded: cut a new branch the moment a PR is merged.**

---

## What shipped

|                                       |                                                                                                                                                                  |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The marking sheet reaches the app** | 410 marks existed, **40 wired**. Now **hooks 26 → 129, drops 9 → 133**. Keyed by AUDIO, not filename, so a rename cannot detach a song from its marks            |
| **Catalog**                           | 33 → **112 songs** (103 loaded, 24 removed at the founder's request)                                                                                             |
| **A curated 25 per dropdown**         | Discord's hard cap. Chosen for what actually mixes: **26 of 59 English vocals pair with no house beat at all**, so alphabetical would have been a third unusable |
| **Every menu song names its artist**  | 0 of 64 uncredited                                                                                                                                               |
| **Discord fit for strangers**         | mod commands hidden, grinding out of the showcase, notices read-only, welcome copy fixed, three empty rooms deleted (9 channels left)                            |
| **Grinder writes its own log**        | after two days writing none                                                                                                                                      |

---

## Do first next session

1. **LISTEN.** Make five mixes. That is the only open question that matters.
2. **Expect the first mix of any NEW pair to take 50–72s, and the same pair again 17–20s.** That is a cold cache, not a fault — the per-pair key measurement is cached in `.f0shift.json` and is protected from every sweep. **61 of 625 pairs are warm.**
3. **Pair within tempo.** The slow vocals (God's Plan 77, SICKO MODE 78, Location 80, Intentions 74) now have only **3 partners each** — Reminder, redrum, Summertime Sadness — because `Faded` came off the menu last. Over a 125 BPM house beat they will decline.
4. **Two songs on the menu carry no marks:** Wari Jawa, Merrygo beat.
5. **Replicate credit is ZERO.** `luther` unloaded; Bollywood sits at 14 of 25 (~11 more loads ≈ 25–70¢).

---

## Verification evidence — all run at handoff, 2026-08-15

| Check                                               | Result                                                                |
| --------------------------------------------------- | --------------------------------------------------------------------- |
| Backend (`pytest services/api -q`)                  | **838 passed** in 217s                                                |
| Discord bot (`pytest services/discord-bot -q`)      | **451 passed, 1 skipped** (was 422/1 at session start; **+29**)       |
| Web (`npm test`)                                    | **78 passed** (9 files)                                               |
| `npm run typecheck`                                 | clean                                                                 |
| `npm run lint`                                      | clean                                                                 |
| `workers/render.py`                                 | **UNTOUCHED** vs `origin/main`                                        |
| `services/api/app/planner/validate.py`              | **UNTOUCHED**                                                         |
| `services/api/app/storage.py`                       | **UNTOUCHED**                                                         |
| `services/api/app/routes/songs.py`                  | **UNTOUCHED**                                                         |
| `services/api/app/config.py`                        | **UNTOUCHED**                                                         |
| `.github/workflows/**`, `conftest.py`, `pytest.ini` | **UNTOUCHED**                                                         |
| Catalog integrity                                   | **112/112** have master + stems + analysis                            |
| Menu                                                | **25 beats / 25 English / 14 Bollywood**, **0 uncredited**            |
| Live Discord channels                               | 9, verified by an INDEPENDENT probe after the deletions               |
| Commands (asked Discord, not assumed)               | `/setup` `/invitefriend` `/applications` **hidden**; 6 others visible |
| Render cost (measured, n=10)                        | **17–20s** warm pair, **50–72s** first time for a pair                |
| Bot / engine                                        | both running; bot logged in 23:59, catalog 112 loaded                 |
| Free disk                                           | **10.6 GB** (was 3.3 GB at its worst)                                 |
| Merge state                                         | `origin/main..HEAD` **empty** — nothing outstanding                   |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **NEEDS FOUNDER SIGN-OFF — a real conflict, unresolved.** `storage.py` says rebuilding a `.pitchshift.wav` costs "~seconds, verified twice". `pitch.py`'s own comment says it does not, and that an evicted pitch cache "can turn a mix that worked yesterday into a mix that refuses to build". Two files disagree and **the stale one drives eviction policy.** Fixing it means editing `storage.py` — a dangerous surface. **NOT DONE.**
- **⚠️ `Member.status` IS USELESS HERE.** Without the privileged presences intent it reads `offline` for **every** member, the founder's own accounts included. It cost a wrong diagnosis this session: a healthy bot was killed and debugged. **To check the bot is up: read `logs/grinder.log`, or fetch the guild's registered commands.**
- **⚠️ `set_permissions` REPLACES an overwrite, it does not edit one.** Read `overwrites_for(role)`, change one field, pass the whole object back. Guarded by `tests/test_lock_welcome_channels.py` (mutation-verified: re-injecting the bug turns 5 red).
- **⚠️ A verifying probe must print the field you did NOT change**, and must not be the same session that made the change. Both rules were learned the hard way tonight: a permission probe that printed only `send_messages` reported success on a change that had hidden three channels, and the channel-deleting script's own closing read still listed a channel it had just deleted.
- **⚠️ After a PR is merged, START A NEW BRANCH.** Commits pushed to a merged branch have no PR and are invisible to the founder. Happened twice this session.
- **The dev dashboard's failure count is partly fiction.** 15 of 230 events are test/profiler rows written into the LIVE `events.db` (ids `aaaa…`/`bbbb…`), including all 8 "something broke on our side". **Real: 18 failures of 215, none since 2026-08-12.** The 08-12 handoff records 191 junk rows deleted for the same reason — **this recurs**; the 08-13 test isolation covered the data dir but NOT `events.db`.
- **Deleting a song is the only irreversible act in this repo.** `scripts/remove_songs.py` destroys paid Replicate stems; 24 songs were removed with the founder's explicit yes. `scripts/delete_channels.py` destroys message history.
- **Pair balance is 509 of 975** workable, down from 788, after five rounds of swaps toward recognisable songs. Deliberate. **If declines rise, this is why** — rebalancing costs nothing.
- **`_EFFECT_POOL_ENABLED` is hard-coded `False`** with no override, so the effect pool has never run in a shipped mix — the same "code exists but never executes" shape as `USE_AI_ARRANGEMENT`.
- **138 leaked `pitch_*` directories** in `services/api/data` (540 KB). Slowly growing, harmless.
- **A `/grind` card is NOT a persistent view.** Any restart kills every open card — worth knowing before restarting while somebody is mid-build.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **The founder caught four things the tests could not.** Invisible songs, hidden channels, a hanging button, and orphaned commits. Every one visible in the product, invisible in the suite.
- **I was wrong about my own measurements before I was wrong about any code.** Reading `status=offline`; printing only the field I had changed; trusting a deleting session's own closing read. Each produced a confident, wrong conclusion in under a minute.
- **One wrong diagnosis was corrected by measurement, not argument.** Low disk was blamed for slow renders; rendering the same pair twice disproved it. The real cost is first-time-per-pair, and that cache is protected from eviction. Freeing disk was still right — at 3.3 GB the janitor was deleting the founder's own finished mixes.
- **Substring matching bit twice in one evening** — `Water`/`WATERmelon Sugar`, `Stay`/`Habits (STAY High)`. Both caught before shipping. The delete tools use exact matching, because there the failure mode is destroying something nobody asked to lose.
- **Tests were updated to a deliberately changed layout, never weakened.** `test_the_server_stays_small_on_purpose` is stricter after the change than before it.
- **Every commit went to a branch, never to `main`.**
