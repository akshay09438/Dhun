# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-12, **session 8/9 — the second voice, built and then FOUNDER-CONFIRMED BY EAR, followed by a `/zuko:goodnight` batch**. Branch `feat/second-grinder-voice`, **PR not opened yet**. `main` is at `2c1e9f9`. **Discord bot 307 passed, backend 768, web 78, typecheck + lint clean.** Nothing is staged and nothing is half-written.

**⚠️ READ FIRST: do NOT run `/setup` on the founder's live Discord server — any flag.** It recreates its default channels beside the ones the founder has renamed. They restored the layout by hand and said **"never change it from this now."** Use `scripts/refresh_copy.py` or do nothing.

**Disk: fine, but it SAWTOOTHS during a sweep — do not panic at a single reading.** Free space swings between about **2.8 GB and 8.7 GB** while the catalog sweep runs: a batch of ten renders consumes roughly 1.2 GB, then the batch cleanup gives it all back. I raised a false alarm at 2.81 GB before realising it was a mid-batch snapshot; it recovered to 7 GB a minute later. **The number to act on is the reading BETWEEN batches, not during one.** The sweep's own guard stops it below 2.5 GB.

---

## THE HEADLINE: two rooms play at the same time, and the founder heard it

Their words after testing: _"it's quiet now, no music started and it works perfectly on both the channels at the same time."_

That is the wall broken. A Discord bot holds one voice connection per SERVER, so until tonight one room had music and every other was silent — and worse, the bot **walked out** of a busy room to serve one person next door. Two identities now hold two rooms.

**What it took, and what the founder's own testing found** (every one of these was invisible to a green test suite):

1. **A ghost bot cost an hour.** A Grinder from 18:34 was still running invisibly after its window was closed. Two bots raced every command; the old one still had the auto-play station and knew nothing about the second room. It explains the music starting on its own, the "only one room can have sound" reply ten minutes after startup said two, and the `Unknown interaction` 404s. **Every symptom looked like a bug in the new code. None were.** `Start-Grinder.bat` now stops any running Grinder before starting one (`scripts/Stop-Other-Grinders.ps1`, narrow enough that it can never touch the engine, 4 tests).
2. **One room read another room's connection.** `/play` in Hollywood_Blends answered about Bollywood_House's music. A room with no identity still has a guild, and that guild's `voice_client` is whatever the main bot is doing elsewhere. Fixed; the old test double had no `.channel`, which is exactly why it slipped through.
3. **Two Grinders in one channel.** A claim and a connection were two different lifetimes: releasing a room handed back the claim and left the identity sitting there, and the next identity to claim it was walked in on top by `play_in`'s `move_to`. `release_voice()` now disconnects too. Three tests, all failed for the right reason before the fix.
4. **The station is GONE, by founder decision.** Their words: it _"is starting a song by itself"_ and _"creating chaos without me giving instruction."_ Removed, not disabled — `play_station`, `air`, `station_number`, `_station_paused`, `_recently_aired`, `store.station_candidates`, and the ten tests that covered only them. **Nothing starts music now except `/grind`, or `/play` picking up what `/stop` paused.** Arriving in a room starts nothing. A mix ending with an empty queue leaves the room rather than sitting connected and silent.
5. **The token scripts were dangerous.** `Set-Grinder-Token.bat` overwrote the whole `.env` — a second run would have silently discarded the server id and all four channel ids. Both scripts now edit one line, genuinely hide the token as it is typed, and refuse the main bot's own token as an "extra".

---

## Documents written tonight (read these before re-deciding anything)

- **`docs/launch-costing-200-500-users.md`** — the founder's ask. Three usage cases side by side. Headline: **listening and members are free**; the only per-mix cost is ~1.5¢ of Claude; a song is paid for once and then free forever. Baseline community ≈ **$20/month on free hosting**. **The cliff is the machine, not the money** — there is no queue in the render path, so a spike fails mixes instead of queueing them. Confidence is stated line by line.
- **`docs/second-voice-hygiene-audit.md`** — the founder's "do both bots follow the same rules" question, answered structurally: the extra identity has no rule code. Four calls total. Includes the grep to re-run it.
- **`docs/panda-not-singing-diagnosis.md`** — see below.

---

## Do first next session

1. **Let the catalog sweep finish, then read its CSV.** It was still running at ~61 of 216 pairs when this was written; disk sawtooths but recovers.
2. **Finish the Panda diagnosis — it is one minute of work.** The plan puts Panda's vocal in 40% of the clip the founder heard, so it is not a planning failure. The measurement that decides between "too quiet" and "never made it into the render" could not run because the mix file was swept off disk mid-sweep. **A mix id is a hash of its inputs, so re-rendering Father Ocean × Panda regenerates a byte-identical file.** Re-render, then run `scratchpad/panda_probe.py`. **Do not touch the vocal chain until that verdict is in.**
3. **Open and merge the PR** for `feat/second-grinder-voice`.
4. **Build the render waiting list.** Agreed with the founder as the next job, and the costing document argues it is now the highest-value thing on the list: no queue exists, so past ~8–10 at once people's mixes fail rather than wait.
5. **The leftover staged card `disk-sweep-floors-and-age`** on `services/api/app/storage.py` is STILL unapplied in `.zuko/goodnight/queue/`. Tonight's disk fall is the argument for it. Surface it; do not apply it.

---

## Verification evidence

| Check                                      | Result                                                      |
| ------------------------------------------ | ----------------------------------------------------------- |
| Discord bot suite                          | **307 passed** _(245 at session start; +62 new, 0 removed)_ |
| Backend, full                              | **768 passed** in 229s                                      |
| Web / typecheck / lint                     | **78 passed** / clean / clean                               |
| `storage.py` / `render.py` / `validate.py` | **untouched**                                               |
| Mutation: shared voice connection          | re-injected → **6 tests failed**, reverted                  |
| Mutation: the `.env`-overwriting behaviour | re-injected → **4 tests failed**, reverted                  |
| Mutation: cross-room connection read       | re-injected → **3 tests failed**, reverted                  |
| **Two rooms with sound at once**           | **FOUNDER-CONFIRMED BY EAR**                                |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The catalog sweep is INCOMPLETE and its old CSV is WRONG.** `scripts/loadtest/failure_sweep.csv` may still be the stale 15:35 file reporting 29.6% — that number was measured on a starved machine and the handoff has warned about it twice. Tonight's re-run got ~60 of 216 pairs before the disk guard stopped it. **The sweep now records WHY each pair failed** (read from the engine's own event log, no engine change), and the early evidence already splits them: some are the quality referee doing its job, some are _"the grinder ran out of room — nothing to do with your songs."_ **Re-run with real disk headroom before believing any catalog failure rate.**
- **A correction to an old finding:** the concurrency diagnosis's #1 problem — "every failure reports the same sentence" — **is no longer true.** The engine now distinguishes a quality rejection from an out-of-resources failure in its own log. That document should be corrected.
- **The disk janitor's deletion path appears to have run for real tonight** (a founder-made mix vanished from disk while free space fell). Previously recorded as never having run. Worth confirming from the engine log before treating as fact.
- **`Add-Grinder-Rooms.bat` has now been run for real by the founder, successfully.** Its `.env`-writing half is tested; the interactive half was exercised by hand.
- **The founder's Discord server is hand-tuned and OFF LIMITS.**
- **95 mixes shipped with a 21–39% tempo stretch.** One heard and approved; the other 94 unheard; the recorded warble threshold is 15%.
- **Queue position with several real people at once has never been seen.**
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes

- **Two wrong calls made and corrected this session.** I told the founder the auto-play was still happening because they had not restarted — they had; the real cause was the ghost bot, found only by listing processes on their machine. And I blamed the `Unknown interaction` errors on them clicking in the console window; that was wrong too, and it sent them chasing nothing. **Both were guesses offered with more confidence than the evidence supported.** The lesson recorded: on their machine, look at their machine before theorising.
- **A promise that was too strong:** "all 245 existing tests pass untouched." 17 reached into single-room internals and were re-pointed (assertions unchanged).
- **A discarded measurement is recorded as discarded** in the Panda diagnosis, rather than being dressed up as a finding.
- Every commit went to a branch, never to `main`.
