# Grinder — the Prompt-DJ Discord bot (beta / demo)

A throwaway, convenience-first demo that lets you make Prompt-DJ mixes **inside Discord**:
type `/mix`, pick two songs, and the finished mix comes back in the channel as a playable
clip with buttons. Built for a quick validation demo — **not** production-hardened.

It reuses the existing Prompt-DJ engine over its local HTTP API (`GET /library`, `POST /mix`,
`GET /mix/{id}/audio`). The bot never touches audio or the mixing logic — all mix quality
lives in the engine.

---

## Go live in 3 steps

**1. Create the Discord app + bot** (once)
- <https://discord.com/developers/applications> → **New Application** → name it (e.g. `Grinder`).
- Left menu → **Bot** → **Reset Token** → **Copy**. Keep it private.
- You do **not** need any Privileged Intents — slash commands don't use them.

**2. Save the token** (once)
- Double-click **`Set-Grinder-Token.bat`** (repo root), paste the token, press Enter.
- This writes `services/discord-bot/.env` (gitignored — never committed). The agent never
  creates this file; you do.

**3. Add the bot + run it**
- Add it to your server with your invite link (Application ID from **General Information**):
  `https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&permissions=3263488&scope=bot%20applications.commands`
- Double-click **`Start-Grinder.bat`** (repo root). It starts the engine, then the bot.
- When the window says `logged in as Grinder`, type **`/mix`** in your server.

> **Instant commands (recommended):** turn on Discord **Developer Mode** (User Settings →
> Advanced), right-click your server → **Copy Server ID**, and add a second line to
> `services/discord-bot/.env`: `DISCORD_GUILD_ID=<that number>`. Slash commands then appear
> in your server immediately instead of taking up to an hour to register globally.

---

## What users do

- **`/mix`** — start typing a **beat** (Song 1) and a **vocals** (Song 2); the list
  autocompletes from the catalog. Send it → a "🎧 Cooking…" card appears, then becomes the
  finished mix (a playable MP3 clip) with:
  - **🔄 Another take** — a different arrangement (up to 5 takes).
  - **🔊 Play in voice** — the bot joins your voice channel and plays it live.
  - **⏹️ Leave voice** — stop and leave.
- **`/songs`** — list the beats and vocals available.

---

## Environment variables (`services/discord-bot/.env`)

| Var | Required | Default | Meaning |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | yes | — | The bot token (secret). |
| `PROMPTDJ_API_BASE` | no | `http://127.0.0.1:8000` | Where the Prompt-DJ engine is. |
| `DISCORD_GUILD_ID` | no | — | Your server id, so `/mix` appears instantly. |

---

## Notes & known limits (it's a demo)

- **Local only.** The bot runs on your PC against the local engine — no cloud, no cost for
  catalog songs (their stems/analysis are already cached). Close the window → bot offline.
- **Clip vs voice.** The in-channel MP3 clip is the reliable path (works everywhere). Voice
  playback needs the `PyNaCl` package; if it doesn't install on this machine, voice degrades
  gracefully and the clip still works. FFmpeg is required (already installed here) for both
  the MP3 transcode and voice.
- **First mix of a pair** can take up to ~a minute (render); after that it's cached/instant.
- **Not production:** no rate limits, no auth, single-process, in-memory state. This is a
  feel-and-validate build, by design.

## Tests

```
services\discord-bot\.venv\Scripts\python.exe -m pytest services\discord-bot\tests -q
```
(Mocked — no token or live Discord needed.)
