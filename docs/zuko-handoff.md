# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-12, **session 8 — `/zuko:goodnight`: THE SECOND VOICE (two listening rooms with sound at the same time)**. Branch `feat/second-grinder-voice`, 5 commits, **PR not opened yet**. `main` is at `2c1e9f9` (PR #34, the application icon, merged by the founder). **All suites green: Discord bot 303, backend 768, web 78, typecheck + lint clean.** Nothing is staged and nothing is half-written.

**⚠️ READ FIRST: do NOT run `/setup` on the founder's live Discord server — any flag, including `refresh_branding:True`.** It recreates its default channels beside the ones the founder has renamed and reorganises their categories. It did exactly that on 2026-08-12; they restored the layout by hand and said **"never change it from this now."** Use `scripts/refresh_copy.py` (dry-run by default, creates no channels) or do nothing. **The server icon is deliberately left un-updated** — it is not worth the risk.

**Voice itself is FOUNDER-CONFIRMED** (2026-08-12): they ran `/grind`, sat in `#Bollywood_House`, and heard a real mix play. Every older hedge about voice being "agent-proven but not heard" is settled. What is _not_ settled is the SECOND identity — see the top of the re-verify list.

---

## Where things stand

**Grinder plays real mixes out loud in real rooms.** `/grind`, `/skip` (including inside a set), `/stop`, `/play`, the language switch and the logo are all confirmed by the founder's own testing. Their words on the tempo question: _"the Silence x Der Lagi Lekin is sounding crazily perfect."_

**Shipped this session (on a branch, not merged): a second Grinder identity, so two rooms can have music at once.**

The wall: a Discord bot application holds ONE voice connection per SERVER, not per room. So while one room played, every other was silent — and when a grind from a second room reached the front of the queue, the bot **walked out** of the room it was in, leaving those people in silence, to serve one person next door. The median mix is 189 s, so five waiting meant the last person waited ~13 minutes for a mix the engine had built in about 30 seconds. Rendering was never the bottleneck (measured ~5.5x parallel).

- **`voices.py`** — a `Voice` is one identity that can hold one room; `VoiceBox` hands them out, **main first**, so zero extras behaves exactly as before.
- **`deck.py`** — a `Deck` is one room's playback (what is on air, position, seams, paused-at, playback token, station memory, the identity it borrowed).
- **`booth.py`** — rewritten as the coordinator over the decks, one global queue, and the server-wide bits.
- **`bot.py::bring_extra_voices_online`** — logs each `GRINDER_ROOM_TOKENS` identity in at startup, drops any that will not come up with one honest line, clears each one's zombie voice session, applies the `# GRINDER` disc per identity.
- **Both `.bat` token scripts rewritten** — see the fixed hazard below.

**The load-bearing detail, if this ever needs debugging:** a channel object belongs to the client that fetched it, and `voice_player.play_in` reads `channel.guild.voice_client`, which is per-client state. Each identity therefore resolves its **own** copy of the room before playing. Get that wrong and both rooms quietly share one connection — which sounds exactly like the bug being fixed and looks perfectly healthy in the log. `voice_player.py` itself is unchanged.

**Founder decisions taken at kickoff** (recorded in `.zuko/goodnight/decisions.json`): each room is a full equal room; the extra is an identical twin (same name, same disc, applied from code); a waiting person is told their position; an empty room holds its voice ~60 s.

**A hazard fixed on the way**, recorded as unfixed in the last handoff: `Set-Grinder-Token.bat` wrote the `.env` with a single `>`, overwriting the whole file. A second run would have silently discarded `DISCORD_GUILD_ID` and all four channel ids, and the bot would have come back half-broken with nothing in the log. Both scripts now edit one line, keep the rest, genuinely hide the token as it is typed, and refuse the main bot's own token as an "extra" (same identity — it would pull the first room's connection away mid-song).

---

## Do first next session

1. **The founder pastes the second token** — Developer Portal → the spare application `1535993733269684334` (or a new one) → Bot → Reset Token → Copy → invite it with See + Connect on the rooms category → `Add-Grinder-Rooms.bat`. **Until this happens the second room is silent, and that is expected.** Full test sheet in `.zuko/goodnight/report.md`.
2. **Open and merge the PR** for `feat/second-grinder-voice`.
3. **The engine's admission control** — the agreed next job, and arguably now the most urgent. There is **no queue and no limit** in the render path (`services/api/app/routes/mix.py` starts a thread per request); past ~8–10 at once the machine runs out of memory and **fails** people's mixes instead of making them wait, reporting the same sentence a genuinely unmixable pair produces. Two working rooms means more simultaneous grinding, so this gets hit sooner.
4. **The leftover staged card `disk-sweep-floors-and-age`** on `services/api/app/storage.py` is still unapplied in `.zuko/goodnight/queue/` — a human-required decision from an earlier night. Surface it; do not apply it.
5. **Re-run the catalog sweep** on an idle machine. The last result is WRONG and is marked as such — three good beats were blamed for a starved laptop. **Wire the failure taxonomy into `failure_sweep.py` first**, or it will report `"?"` again.

---

## Verification evidence

Run at session close. Real output.

| Check                                      | Command                                                           | Result                                  |
| ------------------------------------------ | ----------------------------------------------------------------- | --------------------------------------- |
| Discord bot                                | `.venv-x64/Scripts/python.exe -m pytest -q`                       | **303 passed** _(245 at session start)_ |
| Backend, full                              | `services/api/.venv/Scripts/python.exe -m pytest services/api -q` | **768 passed** in 229s                  |
| Web                                        | `npm test`                                                        | **78 passed**, 9 files                  |
| Typecheck                                  | `npm run typecheck`                                               | clean                                   |
| Lint                                       | `npm run lint`                                                    | clean                                   |
| `storage.py` / `render.py` / `validate.py` | `git diff main...HEAD`                                            | **untouched**                           |
| Mutation: shared voice connection          | re-injected, then reverted                                        | **6 tests failed**, as they should      |
| Mutation: the `.env`-overwriting behaviour | re-injected, then reverted                                        | **4 tests failed**, as they should      |

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **⚠️ THE SECOND ROOM HAS NEVER MADE A SOUND.** Every _decision_ is covered by 58 new tests; a fake voice client is always more forgiving than Discord, and that is how seven bugs shipped past a green suite on 2026-08-11. Status: **built, reviewed, unheard.** Only the founder's token and their ears settle it.
- **`Add-Grinder-Rooms.bat` has still never been run.** It is rewritten and its `.env`-writing half is now tested, but the interactive half (hidden input, the refusals) needs a person at a keyboard. It is step 3 of the test sheet.
- **The founder's Discord server is hand-tuned and OFF LIMITS.** Channels, categories, roles, server icon. Bot avatar and application icon are safe (API-only, no channel side effects); nothing else is.
- **A stale claim was corrected this session:** `speakers.py` said voice "does not work AT ALL on the founder's Windows-ARM machine". That has been untrue since 2026-08-12, when they heard a real mix play (the bot runs on `.venv-x64`, which has `davey`). Watch for other notes written under that assumption.
- **The station has never been heard running on its own.** Its decisions carry tests; `/skip`, `/stop` and `/play` ARE founder-confirmed; the station starting itself after a dry queue is not.
- **Queue position with several real people at once has never been seen.**
- **The catalog sweep result is WRONG** — 29.6% failure, three beats at 18/18, all three succeeded on retry. Do not act on `scripts/loadtest/failure_sweep.csv`.
- **95 mixes shipped with a 21–39% tempo stretch.** The founder has heard one at 29% and approved it. The other 94 are unheard, and the recorded warble threshold is 15%.
- **The disk janitor's deletion path has still never run for real** — only its refusal path.
- **`events.db` holds real rows after two clean-ups** (backups `events.db.backup-robots-2026-08-12` and `events.db.backup-2026-08-12`); both can go once the numbers look right.
- **The GitHub CLI is still not installed**, so PRs are opened by hand.

---

## Process notes from this session

- **A promise made at kickoff that turned out to be too strong:** "all 245 existing bot tests pass untouched." 17 of them reached into the old single-room internals and were **re-pointed at the room's deck with their assertions unchanged**. Not weakened — but not untouched, and it should not have been promised about a change that reshapes exactly what those tests poke at.
- **Every commit went to a branch**, never to `main`. (Two commits went straight to `main` on 2026-08-12; deliberately not rewritten, and not repeated.)
- **The session-7 handoff never reached `main`** — it was committed to `fix/application-icon` after the PR was opened, so PR #34 carried the code but not the notes. Its content (the `/setup` warning, the `.env` hazard, the unheard station) is carried forward here.
