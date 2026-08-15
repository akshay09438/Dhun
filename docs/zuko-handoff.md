# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

**2026-08-16, early hours.** The night after launch. A stranger lost his music, and finding out why turned into an audit, five fixes and a change to how every mix reaches every person.

**MERGED. All nine code commits are on `main` via PR #65** (`ed808c0`) — the founder merged it while this handoff was being written. Only this handoff itself is outstanding, on a **fresh** branch.

⚠️ **AND THAT IS THE TRAP, WALKED INTO AGAIN.** The handoff commit was first pushed to `fix/the-mix-always-reaches-you` — a branch GitHub had already merged and closed, where a new commit is invisible and cannot host another PR. It has happened three times now across sessions. **The rule, once more: the moment a branch is merged it is dead. Start a new one.**

**THE LINK: `https://discord.gg/WJ9b78hFQb`** — permanent, lands on `#read-this-first`.

⚠️ **Never run `/setup` on the live server, any flag.** Use `scripts/refresh_copy.py` for words, `scripts/clear_channels.py` for wiping.

⚠️ **THE ENGINE AND GRINDER ARE BACKGROUND PROCESSES OF A CLAUDE SESSION.** Engine since 21:00 (15 Aug), Grinder restarted three times tonight, last at **23:44:02**. **They die when the machine sleeps.** `Start-Grinder.bat` restarts both.

---

## The one-line version

A grind card is an **ephemeral** Discord message. Discord stores those **nowhere** — so every mix ever made was one app-reload away from gone. It now gets **sent to its maker as a direct message** as well.

---

## What happened, in order

1. **Aashwin's two lost mixes were recovered by hand** and posted to him. Both had been built perfectly. One (#34) was orphaned by a bot restart four seconds before the engine finished; the other (#33) was delivered correctly and deleted by Discord when he reloaded.
2. **A full read-only newcomer audit** — permissions, catalog, copy, config, queue, disk, delivery.
3. **Four fixes from it** (branch `fix/mixes-dont-vanish`, folded into the current branch).
4. **`/zuko:fix` for guaranteed delivery** — the headline change.
5. **Catalog swap**: Bad Guy out, Blinding Lights in, ear-approved.
6. **`#get-shit-done` cleared** to its single intro post.

---

## What shipped

|                                       |                                                                                                                                    |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **A mix is SENT, not shown once**     | `deliver.py` DMs the finished mix. Card keeps its copy too. One retry on a hiccup; DMs-off is explained on the card, never retried |
| **A lost mix can be asked for again** | `/mygrinds` dropdown re-fetches from the engine (`recall.py`). Stores nothing new; the 7-day render window is the limit            |
| **A restart cannot orphan a mix**     | `ref_id` written when the engine ACCEPTS the job, not when it finishes                                                             |
| **📣 recovers instead of promising**  | It used to answer "still arriving" to 22 grinds deleted days earlier                                                               |
| **Seven lines of copy made true**     | Each now guarded by a test that reads the sentence a person is actually sent                                                       |
| **Blinding Lights replaces Bad Guy**  | Already ingested, so zero Replicate spend                                                                                          |
| **The grind room starts fresh**       | 20 messages gone, intro kept, `#best-mixes` untouched                                                                              |

---

## Verification evidence — run 2026-08-16

| Check                                 | Result                                                                                       |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| `pytest services/api -q`              | **845 passed** in 193.95s                                                                    |
| `pytest services/discord-bot -q`      | **555 passed** (was 508 at session start — 47 new)                                           |
| `npm test`                            | **79 passed**, 9 files                                                                       |
| `npm run typecheck` / `npm run lint`  | clean                                                                                        |
| Dangerous surfaces                    | **NONE touched.** `git diff --name-only` vs `origin/main` checked against every glob         |
| Engine `/health`                      | ok, **112 songs, 64 featured**                                                               |
| Picker                                | **25 English vocals**; Bad Guy absent, Blinding Lights present                               |
| Grinder                               | up since 23:44:02, **2 processes** (main + extra voice), no real errors since                |
| **The bug, proven**                   | `fetch_message` on grind #33 and #39 cards → **NotFound both**. Discord never stored them    |
| **Recovery, proven on real data**     | Lucas George's #20, local copy gone → **79,654,348 bytes** back from the engine              |
| **Aashwin's set, proven**             | #39 recovered via the set route, **64,235,224 bytes**, delivered and read back intact        |
| **Blinding Lights, two real renders** | Let Me Love You: `stretch 1.15, forced False`. Rapture: `stretch 1.4035, forced True` (+40%) |
| **First real grind on the new code**  | **#40** (akshay09, 23:32) — completed, **no delivery failure logged**                        |
| `#get-shit-done` after the wipe       | **1 message** (the intro), verified by a SEPARATE process. `#best-mixes` still 8 / 5 audio   |
| Free disk                             | **6.02 GB** — sitting exactly on the cleaner's 6.00 GB line                                  |

---

## Do first next session

1. **Merge the handoff branch** (`docs/handoff-2026-08-16`) — one commit, docs only. The nine code commits are already on `main` via PR #65.
2. **Fix the test-suite log pollution.** It produced fake errors in the live log **five separate times tonight** and each one had to be ruled out by hand — twice it briefly looked like the live bot was broken. `services/discord-bot/tests/` has **no `conftest.py` at all**, which is the root cause. The database IS safe (all 33 test files redirect via `store.reset_for_tests`); only the log and Windows Temp are polluted. **This is now the single biggest drag on working here.**
3. **Make an engine-down failure readable.** If the laptop sleeps, a stranger typing `/grind` sees `Something broke on the way back: [Errno 10061]…`. There is a friendly message for the catalog not loading but not for a mid-render failure.
4. **Anchor Point still talks over its guest** — one line on the guest-verse list, known since 15 Aug, still unfixed. Khalid got 25.5s of a 203s mix.
5. **Watch whether DM delivery actually lands for strangers.** Only ONE real grind (#40, the founder's own) has been through it.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ THE TEST SUITE WRITES INTO THE LIVE `logs/grinder.log`.** Five occurrences tonight. The log cannot be trusted as evidence until this is isolated. It now also writes MY test fixtures' fake errors ("delivery exploded", "grind #39: could not DM the mix").
- **⚠️ GRIND #34 IS PERMANENTLY UNREACHABLE BY THE PRODUCT, and this was a knowing choice.** Its row still has no `ref_id`, so `/mygrinds` cannot fetch it. The rescue post that was its only route back was deleted with the room. The founder was shown the trade and chose to clear anyway. The audio survives at `231732de….bestparts.wav` until roughly **2026-08-22** — a one-field DB write would still restore access before then. **The classifier blocked that write; it needs a human to allow it.**
- **⚠️ FREE DISK IS 6.02 GB, ON the 6.00 GB line.** The cleaner has already evicted once tonight and will keep doing so. Each grind costs ~120–160 MB across both stores; the test suites cost ~1.6 GB per full run. **633 MB of `grind_*` files sit in Windows Temp that nothing sweeps** — the engine's janitor only covers its own data dir.
- **⚠️ MY OWN ERROR, recorded so it is not repeated:** a verification script deleted whatever `recall.audio_for` returned, which for a grind with a live local copy is the STORED file, not a fresh download. It destroyed Aashwin's local copy of grind #39. Recovered from the engine, no lasting harm. **A read-only probe must never delete what it was given.**
- **⚠️ `set_featured`'s "pairs with N/25" is NOT a quality gate.** It counts the safe stretch band only. Blinding Lights scores 6/25 and the founder approved both test renders, including a 40% speed-up. The refined rule: **the octave fold keeps a stretch musical, not the direction** — the one ear-rejected case was the only unfolded one.
- **⚠️ `_EFFECT_POOL_ENABLED` and `USE_AI_ARRANGEMENT` are both hard-coded `False`** — code that has never run in a shipped mix.
- **⚠️ The vocal has no makeup gain** (2:1 compression, 1 dB ducking). Parked since 08-08, resurfaced in the audit, still unfixed.
- **⚠️ `rule_shuffle._resolved_set_base` recurses** and raises past ~1000. Bot counters wrap at 512; the WEB app's `takeNextSetIndex()` is still unbounded — founder was told and chose to leave it.
- **⚠️ Two DIFFERENT people who pick the same pair still share a file** (~1 in 3). Founder was offered the fix and declined.
- **⚠️ The dev dashboard has NO password** and `/admin/*` answers 200 with no credentials. Fine on localhost; the public ngrok link is deliberately OFF and must not go on without `PROMPTDJ_DASHBOARD_TOKEN`.
- **⚠️ `storage.py` / `pitch.py` disagree** about pitch-cache rebuild cost. Dangerous surface, needs founder sign-off. Untouched.
- **⚠️ `Member.status` is useless here**; probe the bot with `scripts/command_probe.py`.
- **⚠️ `set_permissions` REPLACES an overwrite.** Read `overwrites_for`, change one field, write the whole object back.
- **⚠️ A verifying probe must print the field you did NOT change, and must not be the process that made the change.** Used five times tonight and it earned its keep every time — including catching that my own "channel count" check was wrong, not the server.
- **Replicate credit is ZERO.** Any song not already ingested cannot be added. The catalog is 112 songs and that is the ceiling until it is topped up.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.
- **`#the-door` / `#applications` are hidden, not deleted.** History intact.
- **The dashboard's failure count is still partly fiction** — ~35 shown, ~17 real.

---

## Process notes

- **The founder's question was worth more than any test again.** "Is this our issue, or Aashwin leaving the app?" forced a measurement — `fetch_message` on two dead cards — that turned a vague suspicion into a proven root cause and a different, better fix.
- **Recovery was the wrong shape of fix, and the founder said so.** `/mygrinds` asks somebody to know a command at the exact moment they have decided the product lost their work. "By hook or by crook" produced a materially better design.
- **Measuring beat predicting, twice.** The blend score said Blinding Lights would be bad; the founder's ears said otherwise. Before that, the "it must be the ephemeral card" hunch was right but unproven until Discord was actually asked.
- **A dry run caught its own blindness.** `refresh_copy`'s preview silently truncated at the first emoji — 14 lines of 100 — and a review tool that truncates is worse than none.
- **Every live change was dry-run first, applied, then verified by a SEPARATE process.**
- **Every commit went to a branch, never to `main`.**
