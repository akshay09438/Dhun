# A second voice: two listening rooms with sound at the same time

_Design, 2026-08-12. Founder-approved at kickoff. Built overnight on `feat/second-grinder-voice`._

---

## The problem, stated exactly

A Discord bot application holds **one voice connection per SERVER** — not per channel. One Grinder
therefore means one room with sound and every other room silent.

It is worse than "the other room waits", because of how `_play` works today: it re-checks the
owner's room at play time and plays *there*. So when a grind from Hollywood_Blends reaches the front
of the queue, `voice_player.play_in` calls `vc.move_to(channel)` and **the bot physically walks out
of Bollywood_House**, leaving the people in it in silence, to serve one person next door. Three
minutes later it walks back. Both rooms get a broken night.

Measured, in `docs/concurrency-diagnosis.md`: the median mix is **189 s**, so five queued grinds
means the last person waits **~13 minutes** — while the engine finished building their mix in about
30 seconds. This is the "ten to fifteen minute" complaint, and it is voice, not rendering.
Rendering is already ~5.5x parallel and is not the bottleneck.

**A second identity is the only fix.** Not more cores, not a bigger server — Discord's rule is one
connection per identity, exactly like a person can only be in one voice call at a time. Extra bot
applications are free.

## What is already built

`speakers.py` (2026-08-12) already models the extra identities and is covered by 8 tests: a
`SpeakerPool` that hands one speaker to one room, never two speakers to one room, deduplicates
pasted tokens, and returns `None` (a normal answer, not an error) when all are busy.
`botconfig.py` already reads `GRINDER_ROOM_TOKENS`. **Nothing imports either outside the tests.**

Its docstring claims voice "does not work AT ALL on the founder's Windows-ARM machine, so no part
of the audio path here has ever been exercised." **That is now stale** — the founder heard a real
mix play in `#Bollywood_House` on 2026-08-12, running on `.venv-x64` (which has `davey`). Corrected
as part of this work; the second voice IS testable by the founder.

## Founder decisions taken at kickoff

Recorded in `.zuko/goodnight/decisions.json`.

| | Decision |
|---|---|
| **D1** | Room 2 is a **full, equal room** — own queue, own `/skip` `/stop` `/play`, own station. Not a replay-only background station. |
| **D2** | The second identity is an **identical twin**: same name "Grinder", same "# GRINDER" disc, applied from code. The community never learns there are two. |
| **D3** | When every voice is busy, **tell the person where they are in line** — never leave them staring at "grinding…". |
| **D4** | When a room empties, its voice is **held for ~60 s** before being released, so stepping out briefly does not kill the music. |

## The shape of the change

Three ideas, in order of how much they move.

### 1. A `Voice` is a thing a room borrows

New module `voices.py`. A `Voice` is one identity that can hold one connection: the **main bot**
(index 0, always present) or one **speaker** from the existing `SpeakerPool`.

```
VoiceBox.claim(room_id)   -> Voice | None    # main first, then the pool
VoiceBox.release(room_id) -> Voice | None    # idempotent
VoiceBox.holder_of(room_id)
```

Main-first matters: with zero speakers configured the box hands out exactly one voice, and every
behaviour below collapses to precisely what the app does today.

**The one genuinely subtle bit.** A channel object belongs to the client that fetched it.
`voice_player.play_in` does `channel.guild.voice_client`, so handing it a channel from the *main*
bot would connect the *main* bot no matter which voice we think we are using. Each `Voice` therefore
resolves its **own** copy of the room before playing:

```
Voice.resolve(room)  # main -> room itself; speaker -> speaker.client.get_channel(room.id)
```

With that, `voice_player.play_in` needs no change at all — `guild.voice_client` is already
per-client state in discord.py. This is the whole trick, and it is why the audio path stays
untouched.

### 2. One `Deck` per room, instead of one of everything

`Booth` today holds a single copy of: `now_playing`, `station_number`, `_station_paused`,
`_now_path` / `_now_offset` / `_now_started` / `_now_seams`, `_paused_at`, `_play_token`,
`_recently_aired`. All of it moves into a `Deck`, one per room id, each holding the `Voice` it has
borrowed and when it went empty.

`Booth` keeps what is genuinely server-wide: the pinned status message, arrival counting,
`grinds_this_session`, `last_up`, `seam_lookup`, room discovery, `check_config` — and **one global
waiting list**, deliberately (see below).

`skip` / `stop_playback` / `play` all become "find the caller's room, act on that room's deck."
Skipping in Hollywood_Blends cannot reach Bollywood_House because it has no way to name it.

### 3. One waiting list, scheduled per room

The queue stays a **single FIFO list** rather than one per room. When anything frees up, a
scheduler pass walks it in order and starts the first waiting grind whose room can be served —
either its room's deck already holds an idle voice, or a voice can be claimed for it.

Why one list rather than per-room lists: with zero speakers this reproduces today's order exactly
(strict FIFO, one voice), which is the property that lets the existing behaviour tests stand. With
two voices it naturally becomes two independent lanes, because a grind for room B is no longer
blocked by a grind for room A holding the only voice.

**Position shown to the user** (D3) counts only the grinds ahead of them **in their own room** —
that is what actually determines their wait. When the delay is instead "every voice is busy", the
card says that plainly rather than implying their own room is backed up.

## Behaviour, before and after

| | Today (0 extra voices) | With 1 extra voice |
|---|---|---|
| Grind in room A while room A plays | waits | waits (unchanged — one room, one mix at a time, by design) |
| Grind in room B while room A plays | waits, then **drags the bot out of room A** | plays in room B **immediately**, room A undisturbed |
| Room A's track ends | next in the global queue, wherever it is | room A takes the next grind **for room A**, or its own station |
| `/skip` in room B | skips whatever is playing anywhere | skips **room B only** |
| Everyone leaves room A | disconnects when *all* rooms are empty | room A's voice is held ~60 s, then released to whoever needs it |
| No token configured | — | **identical to today, in every respect** |

## Error handling and the states real users hit

- **A speaker fails to log in** (bad token, never invited, revoked): logged as one plain sentence,
  that speaker is dropped from the pool, the bot carries on with the voices that do work. A broken
  second identity must never take the first one down.
- **A speaker cannot see the room** (`get_channel` returns `None` — invited to the server but
  missing View Channel / Connect on that category): the deck releases the voice and the grind falls
  back to waiting for another, rather than dying silently. Logged with the room name, because this
  is the single most likely real-world misconfiguration.
- **Every voice busy:** the card says so, with a position (D3).
- **A room empties and refills inside the grace period:** the music must still be playing. This is
  a *hold*, not a stop-and-restart.
- **All rooms empty:** every voice disconnects, as today.
- **Zero speakers configured:** the default, and the whole design collapses to today's behaviour.

## Testing

The honesty note in `booth.py` stands and applies double here: **a fake voice client is always more
forgiving than Discord**, and seven bugs shipped past a green suite on 2026-08-11. Tests cover
*decisions*, never audio.

- `voices.py`: main-first order; a room never gets two voices; a voice never serves two rooms;
  release is idempotent; zero speakers yields exactly one voice.
- Deck isolation: two decks play at once; `/skip` and `/stop` in one room leave the other's position,
  queue and station untouched.
- Regression, and the most important tests in the change: **with zero speakers, order and behaviour
  are identical to today.** The existing behaviour tests carry this; where they reached into
  `booth.now_playing` they are re-pointed at the deck, with the same assertion.
- The grace period: a room that empties and refills within 60 s does not restart; one that stays
  empty releases its voice.
- The token scripts: writing a token preserves every other setting.

**What no test here can prove:** that audio comes out of a second identity in a second room. That
needs the founder, their token, and their ears. The morning status for it reads
**"built, reviewed, unheard."**

## Also fixed, because this change walks the founder into it

`Set-Grinder-Token.bat` writes the `.env` with a single `>`, which **overwrites the whole file**.
Running it once would silently discard `DISCORD_GUILD_ID` and all four channel/category ids, and the
bot would come back up half-broken with nothing in the log explaining why. `Add-Grinder-Rooms.bat`
has never been run, and reads `%T2%` inside a block before delayed expansion is enabled, so the
third token is silently dropped. Both are fixed here, because this is the change that makes the
founder open them.

## Non-goals

- **Not** more mix-making capacity. A second identity is a second seat, not a second kitchen; the
  engine's ceiling (~8–10 at once, no admission control, failures instead of waiting) is untouched
  and is the agreed next job.
- **Not** more than one mix at a time inside one room — the founder's 2026-08-11 decision stands.
- **Not** any change to how a mix sounds. The engine, the planner and the quality referee are not
  touched by any part of this.
- **Not** a visible second bot: no commands, no posts, no cards from the speaker. It is a speaker,
  not a second Grinder.
