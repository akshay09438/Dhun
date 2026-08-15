# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-15, midday. THE SERVER IS LAUNCHED.** Grinder is a normal, open Discord server with a permanent invite link in the founder's hands. Three bugs were found and fixed, the door feature was removed entirely at the founder's instruction, the rooms were cleared for real users, and a full pre-launch sweep came back clean.

**Everything is merged. `git log origin/main..HEAD` is empty.** All four suites green.

**THE LAUNCH LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, unlimited, lands on `#read-this-first`.

⚠️ **STILL TRUE: never run `/setup` on the live server, any flag.** It recreates default channels beside the founder's renamed ones.

⚠️ **THE ENGINE AND GRINDER RUN AS BACKGROUND PROCESSES OF THAT SESSION** (engine from 10:47, Grinder `Grinder#7345` restarted 11:55 with the Intel venv so voice works). **They die when the machine sleeps.** `Start-Grinder.bat` brings them back. **Do NOT read `logs/grinder.log` as proof of life — see the traps.**

---

## THE ONE THING NOBODY HAS DONE: LISTENED

**Unchanged from the last two handoffs, and now it is the only unanswered question that matters.** 227 hand-marks drive the arranging, the menu was rebuilt, and the founder has heard **two** mixes — the pair sent this session to demonstrate the set-variety fix. Nobody has sat down and judged whether the mixes are actually **good**. Everything else in this file is evidence. This is the gap.

---

## THE HEADLINE: three bugs, and the founder found the cause of the biggest one by asking a question

**1. EVERY SET A PERSON BUILT IN DISCORD CAME OUT IN THE SAME STYLE ORDER, FOREVER.** `bot.py` sent `set_index=0` hard-coded. The engine seeds a set's rule order from `(user_id, set_index)`, and that index is the only thing that varies a person's consecutive sets. Measured: five sets of 5 in a row, all `simple → chop → echo → chop → echo`.

**And a larger bug fell out of the same line: 🔁 Again on a multi-song grind was a no-op.** A set's cache id is built from its pairs and their rules; identical rules meant an identical id, so the engine served the byte-identical file back as a "new take". No test saw either — the only case mentioning `set_index` checks that the API client forwards the number it is handed, never what the bot hands over.

**2. THE VOUCH INVITE DROPPED FRIENDS INTO THE LOBBY** the command promised they would skip. A Discord invite is created against a CHANNEL, and that is where the joiner lands and keeps returning.

**3. AND THE REAL CAUSE OF THE LANDING BUG WAS NEITHER OF THOSE.** After fixing #2 I told the founder it was solved. It was not. The founder asked a plain question — _"will not users land to read this first when invited?"_ — which could not be answered without measuring, and the measurement showed the fix was necessary but nowhere near sufficient: `lock_the_door.py` (13 Aug) had denied `@everyone` view on **every category and channel**, leaving `#the-door` as the only room a roleless newcomer could see. Discord funnelled everyone there regardless of what any invite said.

**The lesson, recorded because it recurs: I reported a fix as complete after proving only the half I had touched.** The founder's question was the whole diagnosis.

---

## What shipped

|                                         |                                                                                                                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Each person gets a real set counter** | `store.set_counters` + `next_set_index()`, claimed per BUILD so 🔁 Again also gets a fresh one. Wraps at 512 — see the recursion trap below |
| **The door is GONE**                    | Founder reversed the whole feature. No form, no lobby, no queue, no approvals                                                               |
| **A normal, open server**               | 12 channels un-locked; a newcomer lands on `#read-this-first`, read-only for strangers; `#the-door`/`#applications` hidden from everyone    |
| **Rooms reset for launch**              | 73 messages cleared from `#get-shit-done`, 1 from `#general`, each keeping its intro post. **`#best-mixes` untouched: 5 messages, 3 mixes** |
| **Invites all land somewhere real**     | Two pointing at now-hidden channels revoked; one permanent launch link created                                                              |
| **New read-only probes**                | `landing_probe.py`, `invite_probe.py`, `command_probe.py`, plus `open_the_server.py` and `clear_channels.py` (both dry-run by default)      |

---

## Do first next session

1. **LISTEN.** Make five mixes and judge them. It is the only open question that matters, and it has now survived three sessions.
2. **Watch the first real users.** Nobody external has used it yet. The dev dashboard at `/#dev` is the place to look.
3. **Expect 50–70s on any brand-new song pair**, ~18s on a repeat. Deferred by explicit founder decision; the pre-warm is scoped and free whenever they want it.
4. **Free disk is 6.91 GB** — under 6 GB the janitor starts clearing finished mixes. Pinned mixes are protected.
5. **The founder's own Discord may still open `#the-door`.** Only they can clear that: click any other channel once. Nothing server-side can reach a cached client.

---

## Verification evidence — all run at handoff, 2026-08-15

| Check                                             | Result                                                                               |
| ------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Backend (`pytest services/api -q`)                | **838 passed** in 216s                                                               |
| Discord bot (`pytest services/discord-bot -q`)    | **467 passed, 1 skipped** (was 451/1 at session start; **+16**)                      |
| Web (`npm test`)                                  | **78 passed** (9 files)                                                              |
| `npm run typecheck` / `npm run lint`              | clean                                                                                |
| All six dangerous surfaces + workflows + conftest | **UNTOUCHED** vs `origin/main`                                                       |
| Secrets                                           | `.env` untracked; no token-shaped string committed                                   |
| Catalog integrity                                 | **112/112** have master + 4 stems + analysis                                         |
| Engine endpoints                                  | `/health` `/library` `/queue` `/docs` + five `/admin/*` all **200**                  |
| **Mix end-to-end**                                | **built in 34.1s, status ready, audio downloaded**                                   |
| Discord commands (asked Discord, not assumed)     | 9 registered; `/setup` `/invitefriend` `/applications` hidden, 6 visible             |
| **Voice, measured per identity**                  | main Grinder **and** extra voice #1: view + connect + speak on **both** rooms        |
| Stranger landing (probe as `@everyone`)           | **`#read-this-first`**; `#the-door` and `#applications` not visible                  |
| Set variety, on the LIVE engine                   | same 3 pairs twice → `echo→chop→simple` then `simple→chop→echo`, both ready          |
| Rule shuffler, 200 consecutive indexes            | **0** back-to-back identical orders; all 6 orderings (sets of 3), all 18 (sets of 5) |
| Channel clear                                     | verified by an **INDEPENDENT** re-read after applying                                |
| Free disk                                         | **6.91 GB**                                                                          |
| Merge state                                       | `origin/main..HEAD` **empty**                                                        |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ THE BOT TEST SUITE WRITES INTO THE LIVE `logs/grinder.log`.** It produced a phantom `extra voice #1 cannot see Hollywood_Blends` line that cost real time this session before a per-identity probe disproved it. **The log is not trustworthy evidence while this is true.** Same family as the `events.db` pollution; the 08-13 test isolation covered the data dir but not either of these.
- **⚠️ `rule_shuffle._resolved_set_base` RECURSES from the index it is given down to 0.** Measured 2026-08-15: **900 fine, 1200 raises `RecursionError`** and the set fails to build. The bot's counter wraps at 512. **The WEB app is still exposed** — `takeNextSetIndex()` in `apps/web/src/lib/user.ts` grows without bound, so a browser reaching ~1000 sets would fail every set from then on, permanently. **The founder was told and chose not to fix it.**
- **⚠️ `Member.status` IS USELESS HERE** (reads `offline` for everyone without the presences intent). To check Grinder is up: `scripts/command_probe.py`, which asks Discord what is registered.
- **⚠️ `set_permissions` REPLACES an overwrite, it does not edit one.** Read `overwrites_for(role)`, change one field, pass the whole object back. `open_the_server.py` does this correctly and prints every field before and after.
- **⚠️ A verifying probe must print the field you did NOT change, and must not be the process that made the change.** Both rules were used this session and both earned their keep.
- **⚠️ AFTER A PR IS MERGED, START A NEW BRANCH.** Followed this session.
- **`door-open-below-30-design.md` IS WRONG ABOUT THE LIVE SERVER.** It states `bearwolf101` holds `@Backup Admin`/Administrator and is excluded from `community_count`. Live: its only role is `@Member`, `administrator=False`, `@Backup Admin` has **0 members**. Moot now the door is gone, but the document is untrue and should not be trusted if the door is ever revived.
- **`OPEN_BELOW` is still 30, deliberately.** The founder asked for 40; that constant only gates when the form appears, so with no form it does nothing. A real joiner cap would be a new build.
- **`#the-door` and `#applications` are HIDDEN, NOT DELETED.** History intact, invisible to everyone. Deleting is irreversible and stays the founder's call. `#the-door` still holds the stale "Grinder is invite only for now" post.
- **The dev dashboard's failure count is still partly fiction.** 34 shown; **17 are real user failures, the most recent 2026-08-12.** The rest are test/profiler/verification rows, including 8 of this session's own.
- **The `storage.py` / `pitch.py` disagreement about pitch-cache rebuild cost is STILL UNRESOLVED** (dangerous surface, needs founder sign-off). Untouched this session.
- **`_EFFECT_POOL_ENABLED` is hard-coded `False`** with no override — the effect pool has never run in a shipped mix.
- **The public web link (ngrok) is deliberately OFF.** The founder chose Discord as the launch surface. **If it is ever turned on, the dev dashboard is UNPROTECTED** — `/admin/*` answered 200 with no credentials. `PROMPTDJ_DASHBOARD_TOKEN` exists and is unset; the code's own comment says not to expose it without setting it.
- **Replicate credit is ZERO.** `luther` unloaded; Bollywood sits at 14 of 25.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **The founder found the cause of the biggest bug by asking a question, not by reporting a symptom.** "Will not users land to read this first when invited?" — I could not answer it without measuring, and the measurement overturned a fix I had already called done.
- **Measuring first prevented a wrong fix.** The founder's report said "the door should not be seen by anyone", which reads as a permissions bug. Permissions were correct. Going straight there would have "fixed" something that worked and shipped the real bug.
- **Three of this session's four discoveries were invisible to the test suite** and visible in the product: the repeating sets, the dead Again button, the lobby landing.
- **Every live change was dry-run first, applied, then verified by a SEPARATE process.** The channel clear and the permission opening both.
- **The `.env` edit went through the approval flow** — plain-language explanation, explicit founder yes, `.zuko/approve.js` recorded and cleared, file backed up first, two lines touched.
- **Every commit went to a branch, never to `main`.**
