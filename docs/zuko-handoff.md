# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-12, **session 7 — the interactive day after the overnight batch**. Branch `fix/application-icon`, 1 commit, pushed, **PR not opened**. `main` is at `4288791`. **All suites green.** Nothing is staged and nothing is half-written.

**⚠️ READ FIRST: do NOT run `/setup` on the founder's live Discord server — any flag, including `refresh_branding:True`.** It recreates its default channels beside the ones the founder has renamed and reorganises their categories. It did exactly that today; they restored the layout by hand and said **"never change it from this now."** Use `scripts/refresh_copy.py` (dry-run by default, creates no channels) or do nothing. **The server icon is deliberately left un-updated** — it is not worth the risk.

---

## Where things stand

**Everything the founder tested today now works, confirmed by them:** voice in a room, `/grind`, `/skip` (including inside a set), `/stop`, `/play`, the language switch, the new logo. Their words on the tempo question: _"the Silence x Der Lagi Lekin is sounding crazily perfect."_

**Shipped this session**

- **`/skip` moves between the tracks of a SET.** A set is one continuous file; the engine already recorded `seam_at` per member and nothing used it. Past the last track it moves on normally.
- **`/stop` remembers the position; `/play` resumes there.** `/stop` also stopped discarding other people's queued grinds — one person could previously bin everybody else's waiting mixes with nobody told why.
- **`/play` exists at all.** The only way into a room used to be finishing a grind while sitting in one.
- **A Bollywood / English vocal switch.** 14 Bollywood vocals to 4 English ones meant a US listener met a wall of unfamiliar names. **It hides, it never blocks** — any beat still mixes with any vocal, so Father Ocean × Tere Bina stays one tap away. Beats are never filtered.
- **`/help` rewritten** — it still described "The Booth", a channel gone since the rooms were split, and never mentioned the playback controls.
- **`/setup` hidden** from anyone without Manage Server.
- **The "# GRINDER" disc** on the bot avatar and the application icon.

**Three bugs the founder's testing found, in order.** Each was invisible to the tests: `/skip` reported success and the track did not play (`vc.stop()` fires the finished-callback, so a station track started **over the top** of the seek — fixed with a playback token); `/play` timed out (Discord kills an interaction unacknowledged for 3 seconds; opening a voice connection takes longer — all three commands now defer); the station could start but never continue (`_advance` read the server off a grind that does not exist during station playback).

---

## Two process failures, both mine

**1. I sent the founder to `/setup` and it wrecked their channel layout.** See the warning at the top. The safe tool already existed and I did not use it. Recorded to agent memory.

**2. Two commits went straight to `main`** (`7a7e79a`, `4288791`) instead of a branch and PR, which the project rules forbid. Caught at handoff. **Deliberately not rewritten** — rewriting shared history is worse than the error. Everything after went to a branch.

**And one correction to a recommendation:** I named the K1 referee as "the one place you are losing good mixes." **It was already fixed** — the f0-based referee landed 2026-08-10 at 22:00 and all four recorded declines are from earlier that same day. 29 mixes since, zero K1 declines. That is the third time this session I read recorded evidence without checking whether it predated its own fix (the others: the launcher, and the catalog sweep).

---

## Do first next session

1. **Open and merge the PR** for `fix/application-icon` — https://github.com/akshay09438/Dhun/compare/main...fix/application-icon
2. **The second listening room.** The founder has a spare Discord application (`1535993733269684334`) that was created during setup and **is not in the server** — it is free and ready to become Grinder 2. They open it → Bot → Reset Token → Copy → invite it, then paste into `Add-Grinder-Rooms.bat` (which is written and committed, but **has never been run**). `speakers.py` is still built, tested, and NOT wired to playback.
3. **Re-run the catalog sweep** on the now-idle machine (14 GB free). The last result is WRONG and is marked as such — three good beats were blamed for a starved laptop. **Wire the failure taxonomy into `failure_sweep.py` first**, or it will report `"?"` again.

---

## Verification evidence

Run at session close. Real output.

| Check                                      | Command                                                           | Result                                                                   |
| ------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Discord bot                                | `.venv-x64/Scripts/python.exe -m pytest -q`                       | **245 passed** _(238 at session start)_                                  |
| Backend, full                              | `services/api/.venv/Scripts/python.exe -m pytest services/api -q` | **768 passed** in 232s                                                   |
| Web                                        | `npm test`                                                        | **78 passed**, 9 files                                                   |
| Typecheck                                  | `npm run typecheck`                                               | clean                                                                    |
| Lint                                       | `npm run lint`                                                    | clean                                                                    |
| `storage.py` / `render.py` / `validate.py` | `git diff`                                                        | **untouched**                                                            |
| The 29% tempo stretch                      | founder listened                                                  | **"crazily perfect"** — the force-tempo concern is CLOSED                |
| Live application icon                      | bot log                                                           | `brand: application icon uploaded from icon.png (52ef9a995dbc88d8)`      |
| Which app is live                          | `application_info()` + `fetch_member`                             | `1535995274705768540` is in the server; `1535993733269684334` is **not** |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **The founder's Discord server is hand-tuned and OFF LIMITS.** Channels, categories, roles, server icon. Bot avatar and application icon are safe (API-only, no channel side effects); nothing else is.
- **`Add-Grinder-Rooms.bat` has never been run.** It edits `.env` in place rather than overwriting — unlike `Set-Grinder-Token.bat`, which **overwrites the whole file** with `>` and would wipe the server and channel ids. That bug is recorded here and NOT yet fixed.
- **The station has never been heard running on its own.** Its decisions carry 24 tests, and `booth.py`'s honesty note stands: a fake voice client is always more forgiving than Discord. `/skip`, `/stop` and `/play` ARE founder-confirmed; the station starting itself after a dry queue is not.
- **Queue position with several real people at once has never been seen.**
- **The catalog sweep result is WRONG** — 29.6% failure, three beats at 18/18, all three succeeded on retry. Do not act on `scripts/loadtest/failure_sweep.csv`.
- **95 mixes shipped with a 21–39% tempo stretch.** The founder has heard one at 29% and approved it. The other 94 are unheard, and the recorded warble threshold is 15%.
- **`events.db` holds 92 real rows** after two clean-ups (228 robot rows removed today, backup at `events.db.backup-robots-2026-08-12`; earlier backup `events.db.backup-2026-08-12`). Both can go once the numbers look right.
- **The disk janitor is running** in the engine started 14:49, cushion 6 GB, 14 GB free — so it has correctly done nothing. Its refusal path was proven on the real disk; its **deletion** path has still never run for real.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.
