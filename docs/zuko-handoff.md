# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-12 (**session 6 — the founder heard it, the launcher bug that nearly stopped them, and the room stops going silent**). Branch `zuko/goodnight-2026-08-12-night2`, **7 commits.** **Nothing is staged and nothing is waiting for you** — that is the difference from last night, and it was engineered rather than lucky. **All suites green.**

**⚠️ THE ONE THING TO READ FIRST: voice is now FOUNDER-CONFIRMED.** The founder ran `/grind`, sat in `#Bollywood_House`, and heard a real mix play. Every hedge in every document about voice being "agent-proven but not heard" is settled. The listening rooms are real.

---

## Where things stand

Two sessions ran today: an interactive morning (`/zuko:start` → debugging → PR #32 merged to `main`) and an overnight batch (`/zuko:goodnight`, 11 tasks, 8 product decisions batched at kickoff — see [.zuko/goodnight/decisions.json](../.zuko/goodnight/decisions.json)).

**The morning's headline was a bug that made the whole app look dead.** Every `/grind` answered _"The application did not respond"_. Nothing was wrong with the bot — **the bot was never running.** `Start-Grinder.bat` contained `echo Installing voice support (best-effort)...` inside an `if/else`; cmd.exe parses a whole block before executing any of it, so the bare `)` closed the block early and the launcher died with `... was unexpected at this time` right after step [1/3], never reaching the line that starts the bot. **The offending line sits on a branch that never runs on a machine that already has its virtualenv** — an unreachable line killing the entire script.

**The lesson, recorded because it cost real time:** the previous handoff flagged that file as _"edited but never run end to end"_. That claim was **true**, and I closed it by re-reading the code and declaring it fine. Reading cannot catch this class of bug. **Running it can, and did, in ninety seconds.** Six tests now pin it, including one that fails if the launcher ever again names a command the bot does not have — it was telling newcomers to type `/mix`, which does not exist.

**The overnight batch then built what voice-working made possible for the first time.**

- **The station.** A room used to play one grind and go **silent**, bot still sitting in it, until the last person left. Now an empty queue falls through to replaying past grinds, ordered favouring 🔥. Walking into a quiet room starts it. **The bot still never judges a mix** — the ordering is over the community's own votes, and is never announced, shown, or hinted at.
- **`/skip` and `/stop`**, open to anyone in the room. Not owner-only (a bad mix whose owner left held the room for three minutes); not a skip-vote (silly with two people).
- **Listening data** — arrivals, departures, time in room. The two gaps recorded as blocking the community phase, and unmeasurable while rooms were quiet.
- **`app/janitor.py`** — a disk timer holding a 6 GB cushion, with a **futility brake** that deletes nothing when clearing everything still would not reach the cushion.
- **`editbudget.py`** — ten cards in one channel now share Discord's per-channel edit allowance.

---

## Two recorded beliefs corrected by measurement

**1. The 25.68s render profile was RIGHT. I was wrong to doubt it.** Earlier in the day I told the founder the real wait was ~67s and that the profile "measured only the mixing stages, not the whole wait." Measured properly end to end (`scripts/loadtest/profile_wait.py`): **felt 25.42s vs 25.04s of stages — 0.38s, 1.5%, unaccounted.** The stages _are_ the wait. 67.4s is the render queue's rolling average across the founder's own **loaded** session (concurrent grinds, the Discord mp3 transcode after the engine says "done", a machine at 5.86 GB free). Both numbers are real; they measure different conditions. **The crop is still 8.53s / 33.5% and still the one worth attacking.**

**2. "ARM cannot do voice" narrows a THIRD time.** `davey` publishes `manylinux_2_17_aarch64`. So: not "ARM", not even "ARM wheels" — **"no _Windows_-ARM wheel; Linux ARM is fully supported."** Free ARM hosting would run voice natively, no emulation trick, no second Python.

---

## Do first next session

1. **Hear the station.** Sit in `#Bollywood_House` with nothing queued and confirm it starts replaying by itself, and that `/skip` and `/stop` do what they say. This is the one thing tonight built that only an ear can confirm.
2. **Reclaim Windows Update's 7.81 GB** — it needs administrator rights the agent does not have. This is the single biggest lever on the founder's disk and it is a few clicks in Disk Cleanup.
3. **Read [hosting-research-2026-08-12.md](hosting-research-2026-08-12.md) and decide.** Free always-on hosting is real and voice is not the obstacle. The recommended next step is a **measurement** (one free instance, one timed render) rather than a migration — because whether 2 shared ARM cores can mix a song is genuinely unknown.
4. **Check the catalog sweep's result** (see parked, below).
5. **Open the PR** for `zuko/goodnight-2026-08-12-night2` and merge. The GitHub CLI is still not installed; use the compare link.

---

## Approval queue

**EMPTY.** Nothing is staged and nothing needs a tap.

That is not because the risky work was skipped — it is because the disk cleaner was **deliberately redesigned** so it did not need to touch a dangerous file. `storage.py` owns the _policy_ (what may be deleted, in what order, what is never touched); the new `janitor.py` owns only the _trigger_ (when to ask). The existing `sweep(target_free_gb=...)` and `sweep(dry_run=True)` already did everything needed. **`services/api/app/storage.py` is byte-identical** — verified, not assumed.

---

## Verification evidence

Run on `zuko/goodnight-2026-08-12-night2`. Real output.

| Check                         | Command                                                            | Result                                             |
| ----------------------------- | ------------------------------------------------------------------ | -------------------------------------------------- |
| Discord bot (Intel venv)      | `.venv-x64/Scripts/python.exe -m pytest -q`                        | **221 passed** _(194 at session start)_            |
| Backend, janitor              | `pytest services/api/tests/test_janitor.py -q`                     | **14 passed**                                      |
| Backend, disk safety          | `pytest services/api/tests -k "storage or disk or sweep or evict"` | **27 passed**                                      |
| `storage.py` untouched        | `git diff HEAD -- services/api/app/storage.py`                     | **empty — byte-identical**                         |
| Engine boots with the janitor | `TestClient(app)` lifespan                                         | starts + stops cleanly                             |
| Janitor, healthy disk (real)  | `janitor.run_once()` at 9.10 GB free                               | `skip-healthy`, **deleted nothing**                |
| Janitor, futile case (real)   | `run_once(cushion_gb=40)`                                          | `skip-futile`, **27.36 GB short, deleted nothing** |
| The real wait                 | `scripts/loadtest/profile_wait.py`                                 | **25.42s felt / 25.04s stages / 1.5% unaccounted** |

---

## Parked, honestly

- **The catalog sweep was STILL RUNNING when this was written.** Started 13:46 on the remaining pairs, batch-by-batch with clean-up between batches (disk oscillated 8.3 → 6.9 → 7.7 GB, exactly as intended). **Its result is not in this document.** The CSV lands at `scripts/loadtest/` — check it before assuming anything about which pairs work. Partial coverage is still useful; a disk-starved run reporting false "bad pair" verdicts is not.
- **Windows Update's 7.81 GB could not be reclaimed** — administrator rights. Only the founder can do it.

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The station has never been heard.** Its decisions are covered by 13 tests, and `booth.py`'s own honesty note applies in full: a fake voice client is always more forgiving than Discord, and that is exactly how bugs shipped past a green suite on 2026-08-11. **No audio has been proven to come out of the station path.** Treat every claim about continuous music as unverified until an ear says otherwise.
- **`/skip` and `/stop` have never been pressed** by a person in a real room.
- **The listening data has never recorded a real session** — only test rows.
- **ZERO real failures have ever been recorded.** After clearing 191 load-test/placeholder rows from `events.db`, exactly **no** failure of any kind remains in the history. The whole failure taxonomy (declined / quality / resources / bug) is unproven outside tests, and the founder's "bad pair" test did not produce one either. Either the catalog is better than feared, or failures are not being recorded — **that is worth finding out.**
- **`speakers.py` is STILL built, tested, and NOT wired.** Multi-room needs founder-created bot identities (`GRINDER_ROOM_TOKENS` is absent from `.env`). One room at a time until then.
- **Disk: ~7.7 GB free and moving** while the sweep runs. `events.db.backup-2026-08-12` (406 KB) is the pre-cleanup copy — delete it once the numbers look right.
- **The engine on port 8000 is the OLD process** (started 12:13, before the janitor existed). The janitor is not actually running yet; it starts with the next engine restart.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.
