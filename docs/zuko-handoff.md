# Zuko handoff — Prompt-DJ

_The single source of truth for "where things stand" between sessions. Dangerous-surface status is written as a CLAIM to re-verify, never as a settled fact._

## Last updated

2026-08-11 (**session 2 — the Grinder Discord community becomes a real place**) — **All suites green. One PR open and NOT merged: [#29](https://github.com/akshay09438/Dhun/pull/29), 9 commits, conflicts already resolved.** Nothing is uncommitted and nothing is unpushed. **One thing is blocked and will not resolve on this machine: voice playback.**

---

## Where things stand

The Discord bot stopped being a command you type and became somewhere to hang out. Everything below is on `feat/grinder-experience` and is live on the founder's server already — the server restructure was applied for real, so **Discord looks like this now whether or not #29 merges.**

- **`/grind` takes no options.** Type it, press enter, a picker opens: choose a beat, choose a vocal, **➕ Add another pair** up to five, **Grind it** stitches them into one continuous set. Controls are greyed out until they can do something, which teaches the order without instructions.
- **Three commands total:** `/grind`, `/mygrinds`, `/help`. `/set` and `/songs` deleted.
- **The bot never judges a mix.** No flavour line, no verdict, no tempo or key. A test reads every card and fails on evaluative or technical wording.
- **🔥 💀 😐 recorded per person per grind** — reactions, not buttons, so they keep working on old grinds and across restarts. Un-reacting really removes the vote.
- **📌 Pin it** carries any grind to `#best-mixes`; pressing twice cannot post twice.
- **The server is rebuilt** — START HERE / GRIND / TALK, every channel's copy written and pinned, `@Session Crew` deleted.
- **`/grind` only works** in the grind category or for someone sitting in a listening room.
- **Listening rooms are a category**, so new rooms work with no config change.

**Catalog: 30 songs** (12 beats, 18 vocals), unchanged. **The engine was not touched** — `render.py`, `validate.py`, `storage.py`, `config.py` and the whole web app are untouched by this session. Nothing about how a mix sounds changed.

---

## In flight

**PR [#29](https://github.com/akshay09438/Dhun/pull/29) — open, mergeable, not merged.** 9 commits, 16 files. Merge conflicts with `main` were resolved in-session (both branches had widened the same `.gitignore` rule). The PR body on GitHub says "No description provided" — the commit messages carry the detail.

The profile banner shipped separately as **PR #28, already merged to `main`.**

---

## BLOCKED — voice playback cannot work on this machine

Not a bug and not a config mistake. **Both available paths are closed on Windows ARM64:**

|                      |                                                                                                                                                                                                                                                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **discord.py 2.5.x** | Requests voice gateway `?v=4`, which Discord has **retired**. The handshake completes, finds the media endpoint, then the socket is closed with **code 4017** — a code that version does not even recognise. Rolled out per voice server, which is why it worked once on the `bom03` endpoint and failed on every attempt afterwards on `bom06`. |
| **discord.py 2.6+**  | Speaks `?v=8` and would work, but raises `RuntimeError: davey library needed in order to use voice` on connect. `davey` is Discord's audio E2EE and has **no distribution for win-arm64 at all** (`pip: from versions: none`); building it needs a Rust toolchain this machine lacks.                                                            |

A `try/except ImportError` around `davey` in `voice_state.py` only decides whether E2EE is offered. **It is not a soft dependency for connecting** — I read it as one, upgraded on that basis, and was proven wrong by the runtime error. Corrected in `requirements.txt` so nobody re-litigates it.

**Now pinned to `discord.py>=2.7`** anyway: everything non-voice is current, and voice fails instantly with a clear message instead of thirty seconds of doomed retries.

**Voice needs an x86 host.** Everything else in the Discord experience works without it.

---

## Do first next session

1. **Merge PR #29**, then `git pull` on `main` (local `main` is behind).
2. **Decide the voice host.** A small cloud box or any x86 machine unblocks listening rooms, the live status message and arrival notes in one move. Until then treat all four as unproven.
3. **Show reactions on the ops dashboard.** They are the product signal and currently land in the bot's own database, which the dashboard does not read. Either the bot posts them to an engine endpoint, or the dashboard reads both.
4. **Clear the test rows from `events.db`** — the `aaaaaaaa`/`bbbbbbbb` placeholder rows still pollute real numbers before launch.

---

## Verification evidence

Every check below was **run at session close** on the merged branch. Real output:

| Check       | Command                                                           | Result                                          |
| ----------- | ----------------------------------------------------------------- | ----------------------------------------------- |
| Discord bot | `services/discord-bot/.venv/Scripts/python.exe -m pytest -q`      | **148 passed** in 3.19s _(75 at session start)_ |
| Backend     | `services/api/.venv/Scripts/python.exe -m pytest services/api -q` | **720 passed** in 192.63s                       |
| Web         | `npm test`                                                        | **78 passed**, 9 files                          |
| Typecheck   | `npm run typecheck`                                               | clean, no output                                |
| Lint        | `npm run lint`                                                    | clean, no output                                |

**Note on running the backend suite:** it must be scoped to `services/api`. From the repo root, pytest also collects the Discord bot's tests, which need the bot's own virtualenv and fail at collection with 5 errors. That is a harness quirk, not a broken suite.

### Verified against the real world, not a fake

- **The server restructure ran live** and is idempotent — a second run created nothing. Both retired channels were confirmed **empty before deletion**.
- **`/grind`, `/mygrinds` and `/help` are the only commands registered**, checked by querying Discord's API directly.
- **Grinder left the `merrygo` server** and is now in exactly one server.
- **Voice worked exactly once** (grind #1, a card reading "PLAYING LIVE IN THE BOOTH · 2 listening" with audio at 0:57/3:08) and never again. See BLOCKED above.

### Three bugs that only real use exposed

Each now has a regression test that was **confirmed to fail against the old code**:

1. A view method named `_refresh` shadowed `discord.ui.View._refresh(components)` and **took the whole bot down** the moment a dropdown was touched. A test now walks every View subclass and fails on any single-underscore method whose signature disagrees with the library's.
2. The "PLAYING LIVE" banner was posted **before** the connection was attempted, so a card claimed a room was listening while the handshake was failing five times over.
3. Force-killing the bot left a **zombie voice session** alive on Discord's side, blocking every later attempt. Startup now declares it is in no voice channel first.

---

## Open escalations and things to RE-VERIFY (claims, not facts)

- **`.env` was edited three times this session** with the founder's explicit approval each time, recorded via `.zuko/approve.js` and cleared after: the three channel ids, the corrected `DISCORD_GUILD_ID` (it still pointed at `merrygo`), and the two category ids. **Claim to re-verify:** the file holds only the token plus those settings and no secret was logged. A backup sits outside the repo in the session scratchpad.
- **The live pinned status message and arrival notes have never been seen working.** They are built and their decisions are unit-tested, but they ride the same voice-state path that could not be exercised. **Treat as unverified.**
- **`⚙️ Rougher` does not exist.** The spec asked for it; the engine exposes no aggression control and the mixing rule is auto-assigned. Building a button that silently re-rolled would have put a second lie on the card. **Needs a decision about changing the engine.**
- **Onboarding, the auto-awarded `First Grind` role, and the weekly `Head Grinder` rotation are not built.** The first is a server setting only the founder can reach; the other two need a scheduler and a week of reaction data.
- **Disk: 9.7 GB free**, `services/api/data` is most of it. A 100-song catalog needs roughly 32 GB and will not fit.
- **The GitHub CLI is not installed**, so PRs cannot be opened from the terminal. Installing it would still need an interactive browser login.
- **Two dev processes were left running** by this session: the engine on port 8000, and the Grinder bot. Both are the founder's normal local setup.
