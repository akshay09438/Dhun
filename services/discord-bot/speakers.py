"""More than one room with sound in it at the same time.

THE WALL THIS EXISTS FOR. A Discord bot application can hold exactly ONE voice connection per
server. Not one per room - one per SERVER. So with a single Grinder, the moment it is playing
in Bollywood_House, every other listening room is silent, and a person sitting in the second
room hears nothing and has no way to know why. Adding rooms does not add capacity; it adds
silent rooms, which is worse than not having them.

More cores cannot fix this and neither can any amount of engine work - it is a property of the
Discord gateway. The ONLY fix is more bot IDENTITIES, and those are free: Discord lets you
create as many applications as you like. Each extra identity is a separate login that can hold
its own voice connection, so three identities means three rooms with sound at once.

WHAT THIS IS AND IS NOT. This is a pool of voice-only clients - extra Grinders that never
listen for commands, never post, and do nothing but sit in one room and play. All the visible
behaviour (the commands, the cards, the reactions) stays with the one main bot, so the
community still sees a single Grinder doing everything. The extras are speakers, not bots.

ZERO CONFIGURED IS THE DEFAULT AND CHANGES NOTHING. With no extra tokens the pool is empty,
`claim` returns None, and the booth falls back to exactly today's behaviour - the main bot,
one room at a time. The founder adds tokens when they want more rooms; nothing breaks until
then, and nothing changes if they never do.

⚠️ UNPROVEN, HONESTLY. Voice does not work AT ALL on the founder's Windows-ARM machine, so no
part of the audio path here has ever been exercised. What IS tested below is every decision this
makes - who gets which room, what happens when they are all busy, that a room is never handed to
two speakers. The playback itself needs a host where voice works at all.
"""
from __future__ import annotations

import logging

log = logging.getLogger("promptdj.discord")


class Speaker:
    """One extra Grinder identity: a login that can hold one voice connection.

    `client` is a discord.Client the caller logs in. It is deliberately typed loosely so the
    decision logic below can be tested with a fake - the real one cannot be exercised on this
    machine at all, and a pool that can only be tested by connecting to Discord is a pool that
    never gets tested."""

    def __init__(self, index: int, token: str, client=None) -> None:
        self.index = index
        self.token = token
        self.client = client
        self.room_id: int | None = None      # the ONE room this speaker is currently holding

    @property
    def free(self) -> bool:
        return self.room_id is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Speaker #{self.index} room={self.room_id}>"


class SpeakerPool:
    """Hands out speakers to rooms. One speaker holds at most one room; one room is held by at
    most one speaker. Both halves matter: two speakers in the same room would play two different
    grinds over each other, which is worse than silence."""

    def __init__(self, tokens: list[str] | None = None, main_token: str | None = None) -> None:
        # Deduplicated, because pasting the same token twice is an easy mistake and the second
        # copy is not a second identity - it is the SAME login, and Discord would simply move the
        # one connection, silently killing the first room mid-grind.
        #
        # `main_token` closes the same hole one step wider, and it is the worse mistake of the two:
        # pasting the MAIN Grinder's token as an extra. Nothing about it looks wrong - the token is
        # valid, the login succeeds - but it is the same identity, so the moment the "second" room
        # started, the FIRST room would go silent mid-song. That reads as a much worse bug than the
        # one this whole feature fixes, so it is refused here rather than discovered live.
        seen: set[str] = set()
        main = (main_token or "").strip()
        self.speakers: list[Speaker] = []
        for tok in tokens or []:
            tok = tok.strip()
            if not tok:
                continue
            if main and tok == main:
                log.warning("speakers: ignoring a token that is the MAIN Grinder's own - it is the "
                            "same identity, not a second one, so it would pull the first room's "
                            "connection away mid-song. Create a NEW application in the Developer "
                            "Portal for each extra room.")
                continue
            if tok in seen:
                log.warning("speakers: ignoring a duplicate token - it is the same identity, "
                            "not a second one, and would steal the first room's connection")
                continue
            seen.add(tok)
            self.speakers.append(Speaker(len(self.speakers) + 1, tok))

    def __len__(self) -> int:
        return len(self.speakers)

    @property
    def rooms_with_sound(self) -> int:
        """How many rooms can have audio at the same time, counting the main bot's one."""
        return 1 + len(self.speakers)

    def holder_of(self, room_id: int) -> Speaker | None:
        return next((s for s in self.speakers if s.room_id == room_id), None)

    def claim(self, room_id: int) -> Speaker | None:
        """A speaker for this room, or None if there is not one to give.

        None is a normal answer, not an error: the caller falls back to the main bot, and if that
        is busy too the grind waits its turn. Returning a speaker that is already elsewhere would
        cut off whatever it is currently playing, which is the one thing a listening room must
        never do to the people sitting in it."""
        held = self.holder_of(room_id)
        if held is not None:
            return held                      # already ours; re-claiming is a no-op, not a second grab
        free = next((s for s in self.speakers if s.free), None)
        if free is None:
            log.info("speakers: all %d busy, room %s falls back to the main bot or waits",
                     len(self.speakers), room_id)
            return None
        free.room_id = room_id
        log.info("speakers: #%d took room %s (%d of %d busy)",
                 free.index, room_id, sum(1 for s in self.speakers if not s.free), len(self.speakers))
        return free

    def release(self, room_id: int) -> Speaker | None:
        """Give a room back. Idempotent - releasing a room nobody holds is fine, which matters
        because a room can empty in several ways at once (last person leaves, playback ends,
        the bot restarts) and none of them should have to check first."""
        held = self.holder_of(room_id)
        if held is not None:
            held.room_id = None
            log.info("speakers: #%d released room %s", held.index, room_id)
        return held

    def release_all(self) -> None:
        for s in self.speakers:
            s.room_id = None


async def bring_online(pool: "SpeakerPool", make_client, *, ready_timeout: float = 30.0,
                       on_ready=None) -> list["Speaker"]:
    """Log each extra identity in, and drop the ones that do not come up.

    A SICK EXTRA MUST NEVER TAKE THE MAIN GRINDER DOWN. There are three ways one fails to arrive and
    all three are things the founder can plausibly do by accident: pasting a token that has since
    been reset, creating the application but never inviting it to the server, or pasting the token of
    an application whose bot user was never created. Each of those must cost exactly one line in the
    log and nothing else - the community still gets the rooms the working identities can cover.

    `make_client` is injected rather than imported so this can be tested without Discord. The real
    one hands back a discord.Client; the tests hand back a fake that can be made to fail on purpose,
    which is the only way any of this gets exercised before it is in front of real people.
    """
    import asyncio

    live: list[Speaker] = []
    for s in pool.speakers:
        client = make_client()
        start = asyncio.ensure_future(client.start(s.token))
        ready = asyncio.ensure_future(client.wait_until_ready())
        done, _pending = await asyncio.wait({start, ready}, timeout=ready_timeout,
                                            return_when=asyncio.FIRST_COMPLETED)
        # `start` finishing FIRST means it died - a successful login never returns; it runs for the
        # life of the process. So "ready won the race" is the only good outcome.
        if ready in done and not start.done():
            s.client = client
            live.append(s)
            log.info("speakers: extra voice #%d is online", s.index)
            if on_ready is not None:
                try:
                    await on_ready(s)
                except Exception:  # noqa: BLE001 - branding an extra is cosmetic
                    log.warning("speakers: could not finish setting up extra voice #%d",
                                s.index, exc_info=True)
            continue

        why = "timed out"
        if start.done():
            exc = start.exception()
            why = f"{type(exc).__name__}: {exc}" if exc else "the login ended immediately"
        log.warning("speakers: extra voice #%d did not come online (%s). Check the token is current "
                    "and that this application has been INVITED to the server. Carrying on without "
                    "it - the rooms it would have covered will wait their turn as before.",
                    s.index, why)
        for task in (start, ready):
            task.cancel()
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass

    pool.speakers = live
    return live


def describe(pool: "SpeakerPool") -> str:
    """One honest line for the startup log, so the founder can see at a glance how many rooms
    can actually have sound - rather than discovering the limit when a room stays quiet."""
    if not len(pool):
        return ("speakers: none configured - ONE room can have sound at a time. "
                "Add GRINDER_ROOM_TOKENS (one extra bot token per additional room) to raise it.")
    return (f"speakers: {len(pool)} extra identities - up to {pool.rooms_with_sound} rooms "
            f"can have sound at the same time")
