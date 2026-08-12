"""ONE room's playback: what is on air in it, where we are in the file, and what happens next.

WHY THIS EXISTS. Until now the booth held one of everything - one thing playing, one waiting list,
one "where you were when you pressed stop", one station. That was correct while a bot could only
ever have sound in one room, which is Discord's rule for one identity. The moment there is a second
identity there must be one of each PER ROOM, or the two rooms trample each other: a /skip in
Hollywood_Blends would move Bollywood_House's track, and /stop in one would strand the other.

So: a Deck is everything that belongs to a single room, and `booth.Booth` became the coordinator
that owns one Deck per room and decides which of them gets a voice.

HONESTY NOTE, inherited and still true: none of the behaviour here can be proven by a test. A fake
voice client is always more forgiving than Discord - that is exactly how seven bugs shipped past a
green suite on 2026-08-11. The tests cover the DECISIONS; the audio needs a real room and a real ear.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import store
import voice_player

log = logging.getLogger("promptdj.discord")

# How many recently-aired grinds one room remembers, so a small catalogue does not loop the same mix
# back to back. Small on purpose: a room with four mixes should still cycle rather than fall silent.
STATION_MEMORY = 10

# Pressing skip twice quickly must not land back on the boundary just crossed.
_SEAM_GUARD_SECS = 2.0


class Deck:
    """One listening room's playback. Owns no Discord objects - it is handed the room each time,
    because a channel object belongs to the client that fetched it and this room may be played
    through a different identity from one track to the next."""

    def __init__(self, room_id: int, booth) -> None:
        self.room_id = room_id
        self.booth = booth                          # the coordinator, for shared services
        self.now_playing = None                     # the GrindContext currently out loud HERE
        self.station_number: int | None = None      # what is on air from the archive, if any
        self._station_paused = False                # set by /stop, so the finish callback obeys it
        self._recently_aired: list[int] = []
        # Where we are in the file that is playing, and where /stop left off. discord.py tracks
        # neither, so each deck keeps both itself.
        self._now_path: str | None = None
        self._now_offset = 0.0
        self._now_started: float | None = None
        self._now_seams: list[float] = []
        self._paused_at: tuple[str, float, list] | None = None
        # WHICH PLAYBACK a finish-callback belongs to. discord.py's vc.stop() FIRES the current
        # source's `after` callback, and voice_player.play_in calls stop() before starting the next
        # thing - so deliberately replacing the audio (a seek, an interrupt) delivers a "track
        # finished" that is not true. Acting on it started something else OVER the top of what had
        # just been started. Every playback carries a token; a callback from a superseded one is
        # ignored.
        self._play_token = 0
        # The identity currently holding this room, and when the room went empty (for the grace
        # period - stepping out for twenty seconds must not kill the music).
        self.voice = None
        self.empty_since: float | None = None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Deck room={self.room_id} playing={self.now_playing is not None}>"

    # -- is anything happening in here ----------------------------------------------------------
    @property
    def busy(self) -> bool:
        """True if this room has something on air - a grind or a station replay."""
        return self.now_playing is not None or self.station_number is not None

    # -- where we are in the current track -------------------------------------------------------
    # discord.py has no notion of a playback position, so each deck keeps its own: where in the file
    # this playback STARTED, and when. Skipping inside a set and picking up where /stop left off are
    # both arithmetic on those two numbers.

    def _begin_playback(self) -> int:
        """Claim the next playback token. MUST be called BEFORE play_in, so that the stale callback
        fired by its internal stop() already looks superseded when it arrives."""
        self._play_token += 1
        return self._play_token

    def _mark_playing(self, path: str, *, offset: float = 0.0, seams: list | None = None,
                      guild=None) -> None:
        if guild is not None:
            self.booth.remember_guild(guild)
        self._now_path = str(path)
        self._now_offset = float(offset)
        self._now_started = time.monotonic()
        self._now_seams = sorted(float(s) for s in (seams or []) if s)

    def elapsed(self) -> float:
        """How far into the current file we are, in seconds."""
        if self._now_started is None:
            return 0.0
        return self._now_offset + max(0.0, time.monotonic() - self._now_started)

    def _next_seam_after(self, secs: float) -> float | None:
        """The start of the NEXT track inside the set that is playing, if there is one.

        A set is ONE continuous audio file, so without these boundaries a skip could only throw away
        the whole set. `seam_at` from the engine's set manifest is where each member's crossfade
        begins, which is exactly the boundary a listener perceives as 'the next track'."""
        for s in self._now_seams:
            if s > secs + _SEAM_GUARD_SECS:
                return s
        return None

    # -- the voice this room has borrowed ---------------------------------------------------------
    async def _channel_to_play_into(self, room):
        """This room, as seen by the identity that is going to play into it - or None if we cannot
        get one.

        THE SUBTLE BIT. A channel object belongs to the client that fetched it, and
        `voice_player.play_in` reaches for `channel.guild.voice_client`, which is per-CLIENT state.
        Handing it the MAIN bot's channel object would connect the MAIN bot however carefully we had
        chosen a different identity - and both rooms would quietly share one connection, which
        sounds exactly like the bug this whole feature fixes."""
        voice = self.booth.voices.claim(self.room_id)
        if voice is None:
            return None                             # every identity is busy; the room waits
        channel = voice.resolve(room)
        if channel is None:
            # Invited to the server but not allowed to see this room is BY FAR the likeliest
            # real-world misconfiguration. Give the voice straight back so it is not held hostage by
            # a room it cannot enter, and say which one, by name.
            log.warning("voices: %s cannot see %s - check it has View Channel and Connect on the "
                        "rooms category", voice.label, getattr(room, "name", self.room_id))
            self.booth.voices.release(self.room_id)
            return None
        self.voice = voice
        return channel

    def release_voice(self) -> None:
        """Give this room's identity back so another room can use it."""
        if self.voice is not None or self.booth.voices.holder_of(self.room_id) is not None:
            self.booth.voices.release(self.room_id)
        self.voice = None

    def voice_client(self, room):
        """The connection actually carrying this room's audio, or None.

        Read through the holding identity rather than off the room we were handed, for the same
        reason as `_channel_to_play_into`: `guild.voice_client` differs per client, and reading the
        main bot's while an extra voice is playing would report 'nothing is playing' in a room that
        is very much playing."""
        voice = self.voice or self.booth.voices.holder_of(self.room_id)
        channel = voice.resolve(room) if voice is not None else room
        guild = getattr(channel, "guild", None) if channel is not None else None
        return getattr(guild, "voice_client", None)

    # -- playing ------------------------------------------------------------------------------------
    async def play_grind(self, ctx, room) -> None:
        """Play one finished grind into this room.

        The room is passed in, re-checked by the caller at play time rather than remembered - a
        queued grind's owner may well have wandered off or moved rooms while they waited, and
        playing to the room they have left is worse than not playing at all."""
        if room is None:
            log.info("booth: grind #%s not played, its owner left the rooms", ctx.number)
            await self.advance()
            return

        channel = await self._channel_to_play_into(room)
        if channel is None:
            # No identity free. Wait rather than cutting somebody else off, and TELL them - a person
            # staring at "grinding..." with no explanation assumes it broke and presses again.
            await self.booth.wait_for_a_voice(ctx, room)
            return

        self.now_playing = ctx
        # CONNECT FIRST, CLAIM SECOND. The banner used to go up before the connection was even
        # attempted, so on 2026-08-11 a card read "PLAYING LIVE IN BOLLYWOOD_HOUSE - 2 listening"
        # while the voice handshake was failing five times over and nothing was audible. A card that
        # says something is happening when it is not is the one thing this interface must never do.
        try:
            tok = self._begin_playback()
            await voice_player.play_in(channel, ctx.audio_path,
                                       on_finished=lambda t=tok: self.advance(t))
            # A SET is one continuous file; its seams are where each member's crossfade begins,
            # which is what a listener hears as "the next track". Without them /skip could only
            # throw away all five.
            seams = await self.booth._resolve_seams(getattr(ctx, "number", None),
                                                    getattr(ctx, "ref_id", None),
                                                    getattr(ctx, "seams", None))
            self._mark_playing(ctx.audio_path, seams=seams, guild=getattr(room, "guild", None))
        except Exception:  # noqa: BLE001 - the room going quiet must never kill the bot
            log.exception("booth: could not play grind #%s in %s", ctx.number,
                          getattr(room, "name", self.room_id))
            self.now_playing = None
            await self.booth._say_it_did_not_play(ctx)
            await self.advance()
            return

        self.booth.grinds_this_session += 1
        self.booth.last_up = ctx.label()
        heard = self.booth.listeners(room)
        log.info("booth: playing grind #%s (%s) in %s to %d listening, through %s",
                 ctx.number, ctx.label(), getattr(room, "name", self.room_id), heard,
                 self.voice.label if self.voice else "?")
        await self.booth._show_live_banner(ctx, heard, room)
        await self.booth.refresh_status(getattr(ctx.interaction, "guild", None))

    async def advance(self, token: int | None = None) -> None:
        """One finished in THIS room, take the next. Called back from the audio player.

        When the queue empties the room does NOT go silent. Until 2026-08-12 it did: the bot sat
        connected and quiet until the last person left, which is a dead room with a bot in it."""
        if token is not None and token != self._play_token:
            # A playback we deliberately replaced has just reported that it ended. It did - but
            # because we stopped it, not because it finished. Acting on this is what stomped on the
            # track a /skip had just started.
            return
        async with self.booth.lock:
            last = self.now_playing
            self.now_playing = None
            nxt = self.booth.take_next_for(self.room_id)
        if nxt is not None:
            await self.booth.start(nxt)
            return

        # NOTHING MORE FOR THIS ROOM. Before starting a replay, check whether another room has a
        # real grind waiting with no identity to play it: a fresh grind anywhere outranks a repeat
        # anywhere. With only the main bot configured this is exactly today's behaviour - the single
        # voice moves on to whoever is next in line.
        if await self.booth.hand_over_if_someone_is_waiting(self):
            return

        # WHICH SERVER. Taking it from the finished grind's interaction works only when a GRIND was
        # playing - while the STATION is on air `now_playing` is None, so that read produced None,
        # `rooms(None)` returned [], and the room went silent for good.
        guild = getattr(getattr(last, "interaction", None), "guild", None) or self.booth.last_guild
        await self.play_station(guild)

    # -- the station ----------------------------------------------------------------------------------
    async def play_station(self, guild) -> None:
        """Keep THIS room alive with what the community has already made.

        Ordered favouring 🔥 reactions - the community's own votes, never Grinder's opinion. THE BOT
        STILL NEVER JUDGES A MIX: nothing about this ordering is announced, shown, or hinted at. A
        visible ranking would prejudice the reaction data, which is the whole product signal.

        Replays straight off disk, so a station hour costs no Replicate credit and writes no new
        file. A mix the disk janitor has swept simply drops out of rotation - hence the exists()
        check rather than trusting the database."""
        if self._station_paused:
            return                      # somebody asked for quiet; stop means stop
        room = self.booth.room_by_id(guild, self.room_id)
        if room is None or self.booth.listeners(room) == 0:
            return                      # nobody listening in here; silence is correct

        try:
            candidates = store.station_candidates()
        except Exception:               # noqa: BLE001 - the station must never break the room
            log.exception("booth: could not read station candidates")
            return

        for row in candidates:
            if row["number"] in self._recently_aired:
                continue
            path = row["audio_path"]
            if not path or not Path(path).exists():
                continue                # swept by the janitor, or never finished
            await self.air(room, row, path)
            return

        # Everything known has aired recently. Forget the history and start the rotation again
        # rather than going quiet - a small room would otherwise fall silent after three mixes.
        if self._recently_aired:
            self._recently_aired.clear()
            log.info("booth: station rotation exhausted in room %s, starting the cycle again",
                     self.room_id)
            return await self.play_station(guild)
        log.info("booth: nothing on disk to air - room %s stays quiet until the next grind",
                 self.room_id)

    async def air(self, room, row, path: str) -> None:
        """Put one past grind on air in this room. Silent by design - no card, no announcement, no
        verdict."""
        channel = await self._channel_to_play_into(room)
        if channel is None:
            return                      # every identity is busy; a replay never outranks a grind
        self._recently_aired.append(row["number"])
        if len(self._recently_aired) > STATION_MEMORY:
            self._recently_aired.pop(0)
        self.station_number = row["number"]
        try:
            tok = self._begin_playback()
            await voice_player.play_in(channel, path, on_finished=lambda t=tok: self.advance(t))
            seams = await self.booth._resolve_seams(row["number"], _ref_of(row), _seams_of(row))
            self._mark_playing(path, seams=seams, guild=getattr(room, "guild", None))
            log.info("booth: station aired grind #%s in %s", row["number"],
                     getattr(room, "name", self.room_id))
        except Exception:  # noqa: BLE001 - a failed replay must not end the station
            log.exception("booth: station could not air grind #%s", row["number"])
            self.station_number = None

    # -- controls -------------------------------------------------------------------------------------
    async def skip(self, room) -> str:
        """Next track IN THIS ROOM. Inside a set that means the NEXT MEMBER of the set, not
        abandoning all five."""
        vc = self.voice_client(room)
        if vc is None or not vc.is_playing():
            return "Nothing is playing right now."

        seam = self._next_seam_after(self.elapsed())
        if seam is not None and self._now_path:
            # Seek forward inside the same file. Stopping and restarting would fire the finish
            # callback and hand the room to the next grind, losing the rest of the set.
            path, seams = self._now_path, list(self._now_seams)
            place = self._now_seams.index(seam) + 2      # human numbering: seam 0 starts track 2
            channel = await self._channel_to_play_into(room)
            if channel is None:
                return "Couldn't skip that one."
            try:
                tok = self._begin_playback()
                await voice_player.play_in(channel, path,
                                           on_finished=lambda t=tok: self.advance(t),
                                           start_at=seam)
            except Exception:  # noqa: BLE001
                log.exception("booth: could not seek to %.2fs", seam)
                return "Couldn't skip that one."
            self._mark_playing(path, offset=seam, seams=seams)
            return f"Skipped to track {place}."

        vc.stop()          # end of the set (or not a set) - the callback takes the next thing
        return "Skipped."

    async def stop(self, room) -> str:
        """Pause THIS room, and REMEMBER WHERE. `/play` picks up from exactly here.

        Deliberately does NOT clear the queue. It used to, which meant one person could bin
        everybody else's waiting grinds without anyone being told why."""
        async with self.booth.lock:
            if self._now_path:
                self._paused_at = (self._now_path, self.elapsed(), list(self._now_seams))
            self.station_number = None
            self._station_paused = True   # do not let the finish callback restart the station
        vc = self.voice_client(room)
        if vc is not None and vc.is_playing():
            vc.stop()
        self._now_started = None
        where = f" at {int(self._paused_at[1]) // 60}:{int(self._paused_at[1]) % 60:02d}" \
            if self._paused_at else ""
        return f"Stopped{where}. Use **/play** to pick up where you left off."

    async def resume(self, room) -> str:
        """Start the music in this room - and bring a Grinder in if one is not already here."""
        vc = self.voice_client(room)
        if vc is not None and vc.is_playing():
            return "Already playing."

        self._station_paused = False

        if self._paused_at:
            path, offset, seams = self._paused_at
            if Path(path).exists():
                channel = await self._channel_to_play_into(room)
                if channel is None:
                    return self.booth.every_voice_busy_line()
                try:
                    tok = self._begin_playback()
                    await voice_player.play_in(channel, path,
                                               on_finished=lambda t=tok: self.advance(t),
                                               start_at=offset)
                except Exception:  # noqa: BLE001
                    log.exception("booth: could not resume")
                    return "Couldn't start it again."
                self._mark_playing(path, offset=offset, seams=seams,
                                   guild=getattr(room, "guild", None))
                self._paused_at = None
                return f"Picking up at {int(offset) // 60}:{int(offset) % 60:02d}."
            # Swept by the disk janitor while it was paused. Say so plainly and move on rather than
            # failing - the mix is gone from disk, not from the world.
            self._paused_at = None

        await self.play_station(getattr(room, "guild", None))
        if self.station_number is None:
            if self.booth.voices.holder_of(self.room_id) is None and self.booth.voices_all_busy():
                return self.booth.every_voice_busy_line()
            return "Nothing to play yet. Grind something."
        return "Playing."

    # -- going quiet ------------------------------------------------------------------------------------
    def go_quiet(self) -> None:
        """Forget what was on air here. Used when the room empties."""
        self.now_playing = None
        self.station_number = None
        self._station_paused = False
        self._now_started = None


def _seams_of(row) -> list:
    """Track boundaries stored with a past grind, or none. Tolerant by design: a row written before
    the column existed, or holding junk, must simply mean "no seams" rather than break the station."""
    import json
    try:
        raw = row["seams"]
    except (KeyError, IndexError, TypeError):
        return []
    if not raw:
        return []
    try:
        vals = json.loads(raw)
        return [float(v) for v in vals if isinstance(v, (int, float))]
    except (TypeError, ValueError):
        return []


def _ref_of(row) -> str | None:
    """The engine's set id for a past grind, if the row has one."""
    try:
        return row["ref_id"]
    except (KeyError, IndexError, TypeError):
        return None
