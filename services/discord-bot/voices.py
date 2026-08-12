"""A voice is a thing a room BORROWS - the scarce resource this whole feature is about.

THE WALL. A Discord bot application holds exactly ONE voice connection per SERVER. Not one per
room - one per identity, for the whole server, exactly like a person can only be in one voice call
at a time. So with a single Grinder, the moment Bollywood_House is playing, Hollywood_Blends is
silent, and worse: when a grind made in Hollywood_Blends reaches the front of the queue the bot
WALKS OUT of Bollywood_House to serve it, leaving the people in there in silence.

More cores cannot fix that and neither can a bigger server. The only fix is more identities, and
Discord gives those away free - see `speakers.py`, which already models the extra ones and decides
which of them covers which room.

WHAT THIS MODULE ADDS. `speakers.py` knows about the EXTRA identities only. The booth needs to talk
about all of them the same way, including the main bot, so it can simply ask "can this room have a
voice?" without caring which identity answers. That is a `Voice`; the `VoiceBox` hands them out.

MAIN FIRST, ALWAYS. With no extra tokens configured the box holds exactly one voice - the main bot -
and every decision the booth makes collapses to precisely what the app did before any of this
existed. That is the property the regression tests hold us to, and it is why nothing changes for the
founder until they choose to paste a second token.

⚠️ THE ONE GENUINELY SUBTLE THING, and the reason `resolve` exists. A channel object belongs to the
client that fetched it. `voice_player.play_in` reaches for `channel.guild.voice_client`, which is
per-CLIENT state - so handing it a channel belonging to the MAIN bot connects the MAIN bot, no
matter which identity we believed we were using. An extra voice must therefore look the room up
through its OWN client before playing. Get this wrong and both rooms quietly share one connection,
which sounds exactly like the bug being fixed and looks perfectly healthy in the log.
"""
from __future__ import annotations

import logging

import speakers as speakers_mod

log = logging.getLogger("promptdj.discord")


class Voice:
    """One identity that can hold one voice connection: the main bot, or one extra speaker.

    The main bot's `room_id` lives here; an extra's lives on its `Speaker`, so `speakers.py` stays
    the single source of truth for the extras and its own tests keep meaning something.
    """

    def __init__(self, index: int, *, speaker=None, client=None) -> None:
        self.index = index                  # 0 is always the main bot
        self.speaker = speaker              # None for the main bot
        self.client = client                # the main bot's client, when it is the main bot
        self._room_id: int | None = None    # only used by the main bot

    # -- which room this identity is currently holding ----------------------------------------
    @property
    def room_id(self) -> int | None:
        return self._room_id if self.is_main else self.speaker.room_id

    @room_id.setter
    def room_id(self, value: int | None) -> None:
        if self.is_main:
            self._room_id = value
        else:
            self.speaker.room_id = value

    @property
    def is_main(self) -> bool:
        return self.speaker is None

    @property
    def free(self) -> bool:
        return self.room_id is None

    @property
    def label(self) -> str:
        """Which identity this is, in words a person can read in a log line."""
        return "the main Grinder" if self.is_main else f"extra voice #{self.speaker.index}"

    def resolve(self, room):
        """THIS identity's own copy of the room, or None if it cannot see it.

        None is a real, expected answer, not a bug: the likeliest misconfiguration by far is an
        extra identity that was invited to the server but never given View Channel / Connect on the
        rooms category. The caller falls back to another voice and says so, rather than failing deep
        inside the audio path where it reads as "voice is broken"."""
        if self.is_main:
            return room
        client = getattr(self.speaker, "client", None)
        if client is None:
            return None                     # this speaker never logged in
        room_id = getattr(room, "id", room)
        try:
            return client.get_channel(room_id)
        except Exception:  # noqa: BLE001 - a sick extra must never take the working ones down
            log.warning("voices: %s could not look up room %s", self.label, room_id, exc_info=True)
            return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Voice {self.label} room={self.room_id}>"


class VoiceBox:
    """Every identity that can hold a room, main bot included. Hands out at most one per room."""

    def __init__(self, pool=None, main_client=None) -> None:
        self.pool = pool if pool is not None else speakers_mod.SpeakerPool([])
        self.main = Voice(0, client=main_client)
        # One stable Voice per Speaker, so a room's holder is the same object every time it is
        # looked up. Built once at startup; the pool's membership never changes at runtime.
        self._extras = [Voice(i + 1, speaker=s) for i, s in enumerate(self.pool.speakers)]
        self._by_speaker = {id(v.speaker): v for v in self._extras}

    @property
    def all_voices(self) -> list[Voice]:
        return [self.main] + self._extras

    @property
    def rooms_with_sound(self) -> int:
        """How many rooms can have audio at the same time, counting the main bot's one."""
        return 1 + len(self.pool)

    def _wrap(self, speaker) -> Voice | None:
        return self._by_speaker.get(id(speaker)) if speaker is not None else None

    def holder_of(self, room_id: int) -> Voice | None:
        if self.main.room_id == room_id:
            return self.main
        return self._wrap(self.pool.holder_of(room_id))

    def claim(self, room_id: int) -> Voice | None:
        """A voice for this room, or None if there is not one to give.

        None means "the room waits", which is a normal answer. Handing back a voice that is already
        playing somewhere else would cut a room off mid-listen - the one thing a listening room must
        never do to the people sitting in it.
        """
        held = self.holder_of(room_id)
        if held is not None:
            return held                     # already ours; re-claiming is a no-op, not a second grab
        if self.main.free:
            self.main.room_id = room_id     # MAIN FIRST - see the module docstring
            log.info("voices: the main Grinder took room %s", room_id)
            return self.main
        got = self._wrap(self.pool.claim(room_id))
        if got is None:
            log.info("voices: every voice is busy, room %s waits (%d rooms can have sound)",
                     room_id, self.rooms_with_sound)
        return got

    def release(self, room_id: int) -> Voice | None:
        """Give a room back. Idempotent, because a room can empty in several ways at once and none
        of them should have to check first."""
        if self.main.room_id == room_id:
            self.main.room_id = None
            log.info("voices: the main Grinder let go of room %s", room_id)
            return self.main
        return self._wrap(self.pool.release(room_id))

    def release_all(self) -> None:
        self.main.room_id = None
        self.pool.release_all()


def describe(box: VoiceBox) -> str:
    """One honest line for the startup log, so the founder learns the limit at startup rather than
    from a room that stays quiet all night."""
    if box.rooms_with_sound <= 1:
        return ("voices: one Grinder - ONE room can have sound at a time. Add GRINDER_ROOM_TOKENS "
                "(one extra bot token per additional room) to raise it.")
    return (f"voices: {box.rooms_with_sound - 1} extra identities - up to {box.rooms_with_sound} "
            f"rooms can have sound at the same time")
