# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-14 (late).** The longest session yet: the catalog went from **33 songs to 112**, the founder's 410 hand-marks reached the app for the first time, the Discord server was tidied for real users, and a full hygiene audit ran. **PR #52 is merged.** Five commits are on `feat/grind-scope-and-welcome-copy` **after** that merge and need a second PR. All four suites green at handoff.

⚠️ **STILL TRUE, KEEP REPEATING: never run `/setup` on the founder's live Discord server, any flag.** It recreates its default channels beside the renamed ones. Use `scripts/refresh_copy.py` (dry run by default).

⚠️ **GRINDER IS RUNNING AS A BACKGROUND PROCESS OF THIS SESSION** (started 2026-08-14 23:27, `Grinder#7345`, 1 server, Intel venv so voice works). Started from the agent shell via `Start-Grinder.bat`, **so it may die when the machine sleeps.** It now writes `services/discord-bot/logs/grinder.log` itself — **check for a recent line there before assuming it is up. Do NOT use `Member.status`; see the trap below.**

---


## Added after the handoff was first written (2026-08-14, very late)

Three last founder changes, all applied and verified live:

1. **`Confusion (Drake)` back on the beat menu, `Faded` off.** Confusion had never left the catalog — it was pushed off the 25 by the evening's pins (six beats had piled up at 120 BPM, including both Moves). **Cost: `Faded` was one of the few slow beats, so God's Plan, SICKO MODE and Intentions drop from 4 partners to 3** (Reminder, redrum, Summertime Sadness). Overall pairings still rose, 498 → 509.
2. **`Levitating Featuring DaBaby (Dua Lipa)` → `Levitating (Dua Lipa)`.**
3. **`#announcements`, `#rules` and `#fred-again-brag` DELETED from the live server.** All three were empty but for Grinder's own placeholder line. Removed from `server_setup.STRUCTURE` too — otherwise `/setup` would recreate them on the next server — and from `lock_welcome_channels.TARGETS`. Three tests that described the old eight-channel layout were updated to the new six; each test's intent is unchanged and `test_the_server_stays_small_on_purpose` is now stricter. **`#read-this-first` was deliberately kept.**

**Re-verified after all three: bot suite 451 passed / 1 skipped. Channel deletion confirmed by an INDEPENDENT probe, not by the script that did it.**

---

## THE HEADLINE: the founder found three things no test did

Each was invisible to the suite, and each was caught by the founder looking at the actual product.

**1. 103 songs were loaded, paid for, and INVISIBLE.** After the big ingest the Discord picker still offered the same **four** English vocals it had before. `bot.py::_vocals_for` filters vocals by `language` and defaults to english; the loader had never written that field. Nothing errored, the manifest looked right, the songs really were there. **English vocals visible: 4 → 59.**

**The check I skipped is the lesson.** Before spending Replicate credit on 103 songs I checked disk, cost, duplicates, marks coverage and analysis quality. **I never checked how a person actually PICKS a song.** One look at `select_option_specs` — `list(songs)[:25]` — would have shown that a Discord dropdown holds 25 options, and the picker would have been fixed _before_ 103 songs were loaded into it.

**2. Locking three channels HID them instead of muting them.** `set_permissions(role, send_messages=False)` **replaces** an overwrite rather than editing it, destroying the `read_messages=True` grant those channels depended on. `#read-this-first`, `#announcements` and `#rules` vanished for every member. **And my verification could not see it** — the probe printed only `send_messages`, so it confirmed the thing that worked and was blind to the thing that broke.

**3. "Add another pair" hung.** Not a bug: a `/grind` card lives in the bot's memory and `GrindBuilderView` is not a persistent view, so **each of my six restarts silently killed every open card.** Measured: the button's work takes **0.2 ms** against a 3000 ms budget.

---

## What shipped

|                                       |                                                                                                           |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **The marking sheet reaches the app** | 410 marks existed, **40 were wired**. Now **hooks 26 → 129, drops 9 → 133**. Keyed by AUDIO, not filename |
| **Catalog**                           | 33 → **112 songs** (103 loaded, 24 removed by founder request)                                            |
| **A curated 25 per dropdown**         | Discord's hard cap; chosen for what actually mixes, not alphabetically                                    |
| **Every menu song names its artist**  | 0 of 64 uncredited                                                                                        |
| **Discord tidied**                    | `/grind` out of `#best-mixes`; mod commands hidden; notice channels read-only; welcome copy fixed         |
| **Grinder writes its own log**        | after two days of writing none                                                                            |

---

## Do first next session

1. **OPEN A SECOND PR.** Five commits sit on `feat/grind-scope-and-welcome-copy` after PR #52 merged: the launcher fix, two beat/vocal swaps, bot logging, and the 24-song removal. **Not in `main`.**
2. **THE BIG UNKNOWN — nobody has listened.** 227 newly-wired marks, a rebuilt menu and four rounds of founder swaps, and **no mix has been heard since any of it.** The mixes _should_ be better; that is unverified.
3. **Expect the first mix of any new pair to take 50–70s** and the same pair again to take 17–20s. That is a cold cache, not a fault. 61 of 625 pairs are warm.
4. **Two songs on the menu carry no marks:** Wari Jawa, Merrygo beat.
5. **Replicate credit is ZERO.** `luther` is unloaded and Bollywood sits at 14 of 25 (~11 more loads ≈ 25–70¢).

---

## Verification evidence — all run at handoff, 2026-08-14 late

| Check                                               | Result                                                                  |
| --------------------------------------------------- | ----------------------------------------------------------------------- |
| Backend (`pytest services/api -q`)                  | **838 passed** in 240s                                                  |
| Discord bot (`pytest services/discord-bot -q`)      | **451 passed, 1 skipped** (was 422/1 at session start; +29)             |
| Web (`npm test`)                                    | **78 passed** (9 files)                                                 |
| `npm run typecheck`                                 | clean                                                                   |
| `npm run lint`                                      | clean                                                                   |
| `workers/render.py`                                 | **UNTOUCHED** vs `origin/main`                                          |
| `services/api/app/planner/validate.py`              | **UNTOUCHED**                                                           |
| `services/api/app/storage.py`                       | **UNTOUCHED**                                                           |
| `services/api/app/routes/songs.py`                  | **UNTOUCHED**                                                           |
| `services/api/app/config.py`                        | **UNTOUCHED**                                                           |
| `.github/workflows/**`, `conftest.py`, `pytest.ini` | **UNTOUCHED**                                                           |
| Catalog integrity                                   | **112/112** have master + 4 stems + analysis; 0 broken                  |
| Marks on the menu                                   | **64/64** wired; 0 gaps                                                 |
| Engine endpoints                                    | `/library` `/queue` `/health` `/docs` all **200**                       |
| Discord commands (asked Discord, not assumed)       | `/setup` `/invitefriend` `/applications` **hidden**; 6 others visible   |
| The three notice channels                           | **can see True, can type False** — verified by an INDEPENDENT probe     |
| Render cost                                         | **17–20s** warm pair, **50–72s** first time for a pair (measured, n=10) |
| Disk                                                | **8.3 GB free** (was 3.3 GB; the janitor has stopped deleting mixes)    |
| Real user failures since 2026-08-12                 | **zero**                                                                |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **A REAL CONFLICT, UNRESOLVED, NEEDS FOUNDER SIGN-OFF.** `storage.py` says rebuilding a `.pitchshift.wav` costs "~seconds, verified twice". `pitch.py`'s own comment says it does not, and that an evicted pitch cache "can turn a mix that worked yesterday into a mix that refuses to build". Two files disagree and **the stale one drives eviction policy**. Fixing it means editing `storage.py` — a dangerous surface. **NOT DONE.**
- **⚠️ `Member.status` IS USELESS HERE.** Without the privileged presences intent it reads `offline` for **every** member, the founder's own accounts included. It cost a wrong diagnosis this session — a healthy bot was killed and debugged. **To check the bot is up: read `logs/grinder.log`, or fetch the guild's registered commands.**
- **⚠️ `set_permissions` REPLACES an overwrite, it does not edit one.** Always read `overwrites_for(role)`, change one field, pass the whole object back. Guarded by `tests/test_lock_welcome_channels.py` (mutation-verified: re-injecting the bug turns 5 red).
- **⚠️ A verifying probe must print the field you did NOT change.** Mine printed only `send_messages` and reported success on a change that had hidden three channels.
- **The dev dashboard's failure count is partly fiction.** 15 of 230 events are test/profiler artifacts in the LIVE `events.db` (ids `aaaa…`/`bbbb…`), including all 8 "something broke on our side". Real: **18 of 215, none since 08-12.** The 08-12 handoff records 191 junk rows deleted for the same reason — **this recurs**; the 08-13 test isolation covered the data dir but NOT `events.db`.
- **Deleting a song is the only irreversible act in this repo.** `scripts/remove_songs.py` destroys paid Replicate stems. 24 songs were removed with the founder's explicit yes.
- **Pair balance is now 498 of 975** workable, down from 788, after four rounds of founder swaps toward recognisable songs. Deliberate. **If declines rise, this is why** — rebalancing costs nothing.
- **`_EFFECT_POOL_ENABLED` is hard-coded `False`** with no override, so the effect pool has never run in a shipped mix — the same "code exists but never executes" shape as `USE_AI_ARRANGEMENT`.
- **138 leaked `pitch_*` directories** in `services/api/data` (540 KB). Slowly growing, harmless.
- **The bot's `/grind` card is NOT a persistent view.** Any restart kills every open card. Worth knowing before restarting while somebody is mid-build.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **The founder caught what the tests could not, three times.** Invisible songs, hidden channels, a hanging button. Every one was visible in the product and invisible in the suite.
- **I was wrong twice about my own measurements before I was wrong about the code.** Reading `status=offline`, and printing only the field I had changed. Both produced confident, wrong conclusions in under a minute.
- **A wrong diagnosis was also corrected by measurement:** low disk was blamed for slow renders; measuring the same pair twice disproved it. The real cause is a per-pair cold cache that is protected from eviction.
- **Substring matching bit twice in one evening** — `Water`/`WATERmelon Sugar`, `Stay`/`Habits (STAY High)`. Both caught before shipping; the delete tool uses start-of-name plus role because the failure mode there is destroying a song nobody asked to lose.
- **Every commit went to a branch, never to `main`.**
