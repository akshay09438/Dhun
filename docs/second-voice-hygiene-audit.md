# Does the second Grinder follow the same rules? — a written audit

_2026-08-12. Founder's question, in their words: "do the hygiene checks that both the bots follow the
same ground rules for everything which we have." Read-only. Every claim below is a grep or a file
read, named so you can check it yourself._

---

## The short answer

**The second Grinder cannot break a rule, because it has no rule code at all.**

It never plans a mix, never renders audio, never judges quality, never picks a song, never reads a
command, never posts a message. It does exactly one thing: **it opens a voice connection and plays a
file it is handed.**

That is not a promise about how carefully it was written — it is a property of what it is wired to.
The audit below is the evidence.

---

## Everything the extra identity is ever asked to do

Grepped across the whole bot for every use of an extra identity's login object
(`grep -rn "\.client\b" voices.py speakers.py bot.py`). The complete list is four calls:

| Where             | The call                                  | What it does                                                                     |
| ----------------- | ----------------------------------------- | -------------------------------------------------------------------------------- |
| `voices.py:103`   | `client.get_channel(room_id)`             | Look up _its own copy_ of a room, so it connects itself rather than the main bot |
| `bot.py:183`      | `self._clear_stale_voice(speaker.client)` | Tell Discord it is not in a call, at startup                                     |
| `bot.py:184`      | `speaker.client.user`                     | Read its own user, to set its picture                                            |
| `speakers.py:165` | `s.client = client`                       | Store the login after it comes online                                            |

**There is no fifth.** No message send, no command tree, no reaction handler, no store write, no HTTP
call to the engine.

## What that rules out, rule by rule

Each of these is a rule the project actually has, and the reason the second identity cannot break it.

| The rule                                                                       | Why the extra identity cannot break it                                                                          |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| **Grinder never judges a mix** — no rating, score, verdict, tempo or key, ever | It cannot post anything. It has no message-sending code path at all.                                            |
| **One vocal, one bassline, no clipping** (the quality referee)                 | It never renders. The referee runs in the engine, before any file exists to play.                               |
| **Never let the LLM touch audio**                                              | It has no planner and no engine client.                                                                         |
| **A mix is one beat + one vocal**                                              | It does not choose songs; it is handed a finished file.                                                         |
| **The Bollywood / English switch hides, never blocks**                         | Filtering happens in the command handler, which only the main bot runs.                                         |
| **One mix at a time per room**                                                 | The queue lives in the coordinator (`booth.py`), which the extras never touch.                                  |
| **Nothing starts by itself**                                                   | Playback is only ever triggered by `/grind`, `/skip` or `/play` — all main-bot commands.                        |
| **The engine's mixing, key-matching, tempo rules**                             | Different process entirely. The bot — either bot — never opens an audio file except to hand its path to ffmpeg. |

## The one rule that IS shared, and how it is enforced

There is exactly one behaviour both identities must agree on: **which room each of them is in.**

That is enforced structurally rather than by convention:

- A room is claimed from one place (`VoiceBox.claim`), which returns the identity already holding
  that room, or a free one, or `None`. It cannot hand the same room to two identities.
- Releasing a room now also **disconnects** that identity (`Deck.release_voice`), so a claim and a
  seat can no longer drift apart — that drift is what produced the founder-reported "two Grinders in
  one channel" bug, and there are three tests that fail if it returns.
- A room with no identity of its own **cannot read another room's connection** — added after the
  founder hit exactly that.

## Where they deliberately differ

Two differences, both intentional, both founder decisions:

1. **Only the main Grinder talks.** Cards, `/help`, the pinned status, arrival notes, reactions — all
   main bot. The community sees one Grinder. _(founder decision: an identical twin)_
2. **Each identity keeps its own record of the picture it uploaded.** Same artwork, separate
   bookkeeping, because Discord's avatar rate limit is counted per bot.

## What this audit does NOT cover

- **That audio actually comes out of the second identity.** Proven by the founder's own ears on
  2026-08-12, not by this audit.
- **Behaviour under many simultaneous real people.** Never observed.
- **Anything in the mixing engine.** Untouched by this work and out of scope here.

## How to re-run this yourself

```bash
grep -rn "\.client\b" services/discord-bot/voices.py services/discord-bot/speakers.py services/discord-bot/bot.py
```

If that ever returns a fifth line, an extra identity has been given a new power, and this document
needs re-reading before it ships.
