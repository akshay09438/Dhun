"""The listening rooms - where grinds play out loud, and the sign on the door.

The problem this solves: voice was invisible. Someone saw a channel with a speaker icon, had no
way to tell whether anything was happening, so they never joined, so nothing ever happened. Two
fixes live here.

1. A grind made by somebody sitting in one of the rooms plays THERE automatically. No button.
   Everyone in that room hears it at the same second, which is the entire product - shared surprise.
2. A single pinned message in the grind channel that always says whether the room is live, so the
   answer to "is anything happening" is visible from the text channel.

ONE GRIND AT A TIME (founder decision 2026-08-11). A second grind finished while one is playing
waits its turn rather than cutting in. A room where the music restarts every ninety seconds is
worse than a room with a short queue, and being interrupted mid-listen spoils the surprise for
everyone already there.

HONESTY NOTE: none of the behaviour in this file can be proven by a test. A fake voice client will
always be more forgiving than Discord (that is exactly how seven bugs shipped past a green suite on
2026-08-11). The unit tests below the line cover the decisions - who plays next, when to sleep,
what the sign says - and the real playback needs a real room.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import discord

import store
import ui
import voice_player
from botconfig import load_config

log = logging.getLogger("promptdj.discord")
CFG = load_config()

# How many people must be in the room before the sign says LIVE. One person in a room is not a
# session; two is. Configurable because it is a taste call, not a fact.
LIVE_THRESHOLD = 2

# Arrival notes get boring fast in a busy room, so only the first few are announced.
ANNOUNCE_FIRST = 1
ANNOUNCE_EVERY = 3

# How many recently-aired grinds the station remembers, so a small catalogue does not loop the
# same mix back to back. Small on purpose: a room with four mixes should still cycle rather than
# fall silent, and the rotation resets once everything known has aired.
STATION_MEMORY = 10

# Pressing skip twice quickly must not land back on the boundary just crossed. Small enough that a
# deliberate double-skip still moves two tracks.
_SEAM_GUARD_SECS = 2.0


def _seams_of(row) -> list:
    """Track boundaries stored with a past grind, or none. Tolerant by design: a row written
    before the column existed, or holding junk, must simply mean "no seams" rather than break the
    station."""
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


class Booth:
    """All Booth state in one object so nothing is a module-level global that a test cannot reset."""

    def __init__(self) -> None:
        self.queue: list = []                       # GrindContexts waiting their turn
        self.now_playing = None                     # the GrindContext currently out loud
        self.grinds_this_session = 0
        self.last_up: str | None = None
        self.status_message: discord.Message | None = None
        self._arrivals = 0
        self._lock = asyncio.Lock()
        # Station state. `station_number` is what is on air from the archive (None when a live
        # grind is playing). `_station_paused` is set by /stop so the finish callback does not
        # immediately start the station again - stop must mean stop.
        self._recently_aired: list[int] = []
        self.station_number: int | None = None
        self._station_paused = False
        # Where we are in the file that is playing, and where /stop left off. discord.py tracks
        # neither, so the booth keeps both itself.
        self._now_path: str | None = None
        self._now_offset = 0.0
        self._now_started: float | None = None
        self._now_seams: list[float] = []
        self._paused_at: tuple[str, float, list] | None = None
        self._last_guild = None      # so _advance still knows the server when the STATION ends
        # Looks up a set's track boundaries from the engine, given its set id. Injected by bot.py
        # so the booth needs no HTTP client of its own and stays unit-testable. None = no lookup.
        self.seam_lookup = None

    # -- the rooms ------------------------------------------------------------------------
    def is_a_room(self, channel) -> bool:
        """True for any voice channel sitting under the configured rooms category.

        A CATEGORY rather than one channel id, because the founder adds and renames rooms as the
        community grows. On 2026-08-11 the single configured voice channel was deleted and replaced,
        the id stopped matching anything, and playback silently stopped working with nothing in the
        log. A category survives that; a channel id does not."""
        if channel is None or not CFG.rooms_category_id:
            return False
        if not hasattr(channel, "connect") or not hasattr(channel, "members"):
            return False        # a text channel has members but cannot be joined
        cat = getattr(channel, "category", None)
        cat_id = getattr(cat, "id", None) or getattr(channel, "category_id", None)
        return cat_id == CFG.rooms_category_id

    def room_of(self, member):
        """The listening room this person is sitting in, or None if they are not in one."""
        state = getattr(member, "voice", None)
        channel = getattr(state, "channel", None) if state else None
        return channel if self.is_a_room(channel) else None

    def rooms(self, guild) -> list:
        if guild is None or not CFG.rooms_category_id:
            return []
        return [c for c in getattr(guild, "voice_channels", []) if self.is_a_room(c)]

    def listeners(self, channel) -> int:
        """People in one room, not counting Grinder itself - the bot is not an audience."""
        if channel is None:
            return 0
        return len([m for m in channel.members if not m.bot])

    # -- playing -------------------------------------------------------------------------
    async def on_grind_finished(self, ctx) -> None:
        """Called when a grind's audio is ready. Plays it out loud only if its owner is sitting in
        one of the rooms - a grind made from a text channel by someone who is not in a room is a
        private thing and must not seize anybody's speakers."""
        room = self.room_of(ctx.interaction.user)
        if room is None or ctx.audio_path is None:
            return

        # A fresh grind un-pauses the station: asking for music is asking for music.
        self._station_paused = False

        interrupt_station = False
        async with self._lock:
            if self.now_playing is not None:
                self.queue.append(ctx)
                await self._mark_queued(ctx)
                log.info("booth: grind #%s queued behind #%s (%d waiting)",
                         ctx.number, self.now_playing.number, len(self.queue))
                return
            if self.station_number is not None:
                # An archive replay is on air. A fresh grind OUTRANKS it - someone who just made a
                # thing should hear their thing, not wait out a repeat of last week's.
                # ORDER MATTERS: queue this grind BEFORE cutting the replay short. Stopping first
                # would let the finish callback reach _advance, find an empty queue, and start
                # another replay - racing this one.
                self.queue.append(ctx)
                self.station_number = None
                interrupt_station = True

        if interrupt_station:
            vc = getattr(room.guild, "voice_client", None)
            if vc is not None and vc.is_playing():
                vc.stop()               # callback -> _advance -> pops the grind queued above
            else:
                await self._advance()   # nothing actually playing; move it along ourselves
            return

        await self._play(ctx)

    async def _play(self, ctx) -> None:
        """Play into the room its owner is in RIGHT NOW, re-checked at play time rather than
        remembered - a queued grind's owner may well have wandered off or moved rooms while they
        waited, and playing to the room they have left is worse than not playing at all.

        A bot can hold only ONE voice connection per server, so while this is playing, a grind
        finishing in a different room waits its turn rather than interrupting."""
        room = self.room_of(ctx.interaction.user)
        if room is None:
            log.info("booth: grind #%s not played, its owner left the rooms", ctx.number)
            await self._advance()
            return

        self.now_playing = ctx
        # CONNECT FIRST, CLAIM SECOND. The banner used to go up before the connection was even
        # attempted, so on 2026-08-11 a card read "PLAYING LIVE IN BOLLYWOOD_HOUSE - 2 listening"
        # while the voice handshake was failing five times over and nothing was audible. A card
        # that says something is happening when it is not is the one thing this interface must
        # never do.
        try:
            await voice_player.play_in(room, ctx.audio_path, on_finished=self._advance)
            # A SET is one continuous file; its seams are where each member's crossfade begins,
            # which is what a listener hears as "the next track". Without them /skip could only
            # throw away all five.
            seams = await self._resolve_seams(getattr(ctx, "number", None),
                                              getattr(ctx, "ref_id", None),
                                              getattr(ctx, "seams", None))
            self._mark_playing(ctx.audio_path, seams=seams, guild=room.guild)
        except Exception:  # noqa: BLE001 - the room going quiet must never kill the bot
            log.exception("booth: could not play grind #%s in %s", ctx.number, room.name)
            await self._say_it_did_not_play(ctx)
            await self._advance()
            return

        self.grinds_this_session += 1
        self.last_up = ctx.label()
        heard = self.listeners(room)
        log.info("booth: playing grind #%s (%s) in %s to %d listening",
                 ctx.number, ctx.label(), room.name, heard)
        await self._show_live_banner(ctx, heard, room)
        await self.refresh_status(ctx.interaction.guild)

    async def _say_it_did_not_play(self, ctx) -> None:
        """The grind itself is fine and the clip is attached - only the out-loud part failed. Say
        exactly that, rather than leaving a card implying a room heard something it did not."""
        if ctx.message is None:
            return
        embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                               pairs=ctx.named_pairs(), total_secs=ctx.duration,
                               voice_failed=True)
        try:
            await ctx.message.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def _advance(self) -> None:
        """One finished, take the next. Called back from the audio player.

        When the queue empties the room does NOT go silent. Until 2026-08-12 it did: the bot sat
        connected and quiet until the last person left, which is a dead room with a bot in it, not
        a listening room. Now it falls through to the station."""
        async with self._lock:
            last = self.now_playing
            self.now_playing = None
            nxt = self.queue.pop(0) if self.queue else None
        if nxt is not None:
            await self._play(nxt)
            return
        # WHICH SERVER. Taking it from the finished grind's interaction works only when a GRIND
        # was playing - while the STATION is on air `now_playing` is None, so that read produced
        # None, `rooms(None)` returned [], and the room went silent for good. `_last_guild` is set
        # every time anything is put on air, so it survives both cases.
        guild = getattr(getattr(last, "interaction", None), "guild", None) or self._last_guild
        await self._play_station(guild)

    # -- the station ---------------------------------------------------------------------------
    async def _play_station(self, guild) -> None:
        """Keep the room alive with what the community has already made.

        Ordered favouring 🔥 reactions - the community's own votes, never Grinder's opinion. THE
        BOT STILL NEVER JUDGES A MIX: nothing about this ordering is announced, shown, or hinted
        at. A visible ranking would prejudice the reaction data, which is the whole product signal.

        Replays straight off disk, so a station hour costs no Replicate credit and writes no new
        file. A mix the disk janitor has swept simply drops out of rotation - hence the exists()
        check rather than trusting the database.
        """
        if self._station_paused:
            return                      # somebody asked for quiet; stop means stop
        room = self._busiest_live_room(guild)
        if room is None:
            return                      # nobody listening; silence is correct

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
            await self._air(room, row, path)
            return

        # Everything known has aired recently. Forget the history and start the rotation again
        # rather than going quiet - a small room would otherwise fall silent after three mixes.
        if self._recently_aired:
            self._recently_aired.clear()
            log.info("booth: station rotation exhausted, starting the cycle again")
            return await self._play_station(guild)
        log.info("booth: nothing on disk to air - the room stays quiet until the next grind")

    async def _resolve_seams(self, number: int | None, ref_id: str | None,
                             stored: list | None) -> list:
        """Track boundaries for what is about to play, looked up if they were never recorded.

        WHY THIS IS NOT JUST `stored`: seams began being written on 2026-08-12, so every set made
        before that has none - and /skip on one of them silently degraded to "stop", which is
        exactly what the founder hit. The engine has always known them (`seam_at` per member), so
        ask it once and write the answer back rather than depending on when a grind happened to be
        made."""
        if stored:
            return stored
        if not ref_id or self.seam_lookup is None:
            return []
        try:
            seams = await self.seam_lookup(ref_id)
        except Exception:  # noqa: BLE001 - no boundaries is a worse skip, not a broken room
            log.warning("booth: could not look up seams for %s", ref_id, exc_info=True)
            return []
        if seams and number:
            try:
                store.set_seams(number, seams)      # so it is a lookup once, not every play
            except Exception:  # noqa: BLE001
                pass
        return seams or []

    async def _air(self, room, row, path: str) -> None:
        """Put one past grind on air. Silent by design - no card, no announcement, no verdict."""
        self._recently_aired.append(row["number"])
        if len(self._recently_aired) > STATION_MEMORY:
            self._recently_aired.pop(0)
        self.station_number = row["number"]
        try:
            await voice_player.play_in(room, path, on_finished=self._advance)
            seams = await self._resolve_seams(row["number"], _ref_of(row), _seams_of(row))
            self._mark_playing(path, seams=seams, guild=room.guild)
            log.info("booth: station aired grind #%s in %s", row["number"], room.name)
        except Exception:  # noqa: BLE001 - a failed replay must not end the station
            log.exception("booth: station could not air grind #%s", row["number"])
            self.station_number = None

    def _busiest_live_room(self, guild):
        """The room with the most people in it, or None if nobody is listening anywhere."""
        best, best_n = None, 0
        for room in self.rooms(guild):
            n = self.listeners(room)
            if n > best_n:
                best, best_n = room, n
        return best

    # -- controls ------------------------------------------------------------------------------
    # -- where we are in the current track ------------------------------------------------------
    # discord.py has no notion of a playback position, so the booth keeps its own: where in the
    # file this playback STARTED, and when. Everything below - skipping inside a set, and picking
    # up where /stop left off - is arithmetic on those two numbers.

    def _mark_playing(self, path: str, *, offset: float = 0.0, seams: list | None = None,
                      guild=None) -> None:
        if guild is not None:
            self._last_guild = guild
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

        A set is ONE continuous audio file, so without these boundaries a skip could only throw
        away the whole set. `seam_at` from the engine's set manifest is where each member's
        crossfade begins, which is exactly the boundary a listener perceives as 'the next track'.

        A small guard so pressing skip twice quickly does not land back on the seam just passed.
        """
        for s in self._now_seams:
            if s > secs + _SEAM_GUARD_SECS:
                return s
        return None

    async def skip(self, member) -> str:
        """Next track. Inside a set that means the NEXT MEMBER of the set, not abandoning all five.

        ANYONE IN THE ROOM MAY SKIP (founder decision 2026-08-12). Deliberately not owner-only: a
        bad mix whose owner has wandered off would otherwise hold the room for three minutes. At
        this scale social pressure handles abuse better than a vote does.
        """
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then skip."
        vc = getattr(room.guild, "voice_client", None)
        if vc is None or not vc.is_playing():
            return "Nothing is playing right now."

        seam = self._next_seam_after(self.elapsed())
        if seam is not None and self._now_path:
            # Seek forward inside the same file. Stopping and restarting would fire the finish
            # callback and hand the room to the next grind, losing the rest of the set.
            path, seams = self._now_path, list(self._now_seams)
            place = self._now_seams.index(seam) + 2      # human numbering: seam 0 starts track 2
            try:
                await voice_player.play_in(room, path, on_finished=self._advance, start_at=seam)
            except Exception:  # noqa: BLE001
                log.exception("booth: could not seek to %.2fs", seam)
                return "Couldn't skip that one."
            self._mark_playing(path, offset=seam, seams=seams)
            return f"Skipped to track {place}."

        vc.stop()          # end of the set (or not a set) - the callback takes the next thing
        return "Skipped."

    async def stop_playback(self, member) -> str:
        """Pause, and REMEMBER WHERE. `/play` picks up from exactly here.

        Deliberately does NOT clear the queue any more. It used to, which meant one person could
        bin everybody else's waiting grinds without anyone being told why - a much bigger hammer
        than the founder was choosing when they said 'anyone in the room can stop'.
        """
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then stop."
        async with self._lock:
            if self._now_path:
                self._paused_at = (self._now_path, self.elapsed(), list(self._now_seams))
            self.station_number = None
            self._station_paused = True   # do not let the finish callback restart the station
        vc = getattr(room.guild, "voice_client", None)
        if vc is not None and vc.is_playing():
            vc.stop()
        self._now_started = None
        where = f" at {int(self._paused_at[1]) // 60}:{int(self._paused_at[1]) % 60:02d}" \
            if self._paused_at else ""
        return f"Stopped{where}. Use **/play** to pick up where you left off."

    async def play(self, member) -> str:
        """Start the music in the room this person is sitting in - and bring Grinder in if it is
        not already there.

        This is the command that was missing: before it, the ONLY way to get Grinder into a room
        was to finish a grind while sitting in one. Somebody who just wanted music had nothing to
        type.
        """
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then play."

        vc = getattr(room.guild, "voice_client", None)
        if vc is not None and vc.is_playing():
            return "Already playing."

        self._station_paused = False

        if self._paused_at:
            path, offset, seams = self._paused_at
            if Path(path).exists():
                try:
                    await voice_player.play_in(room, path, on_finished=self._advance,
                                               start_at=offset)
                except Exception:  # noqa: BLE001
                    log.exception("booth: could not resume")
                    return "Couldn't start it again."
                self._mark_playing(path, offset=offset, seams=seams)
                self._paused_at = None
                return f"Picking up at {int(offset) // 60}:{int(offset) % 60:02d}."
            # Swept by the disk janitor while it was paused. Say so plainly and move on rather
            # than failing - the mix is gone from disk, not from the world.
            self._paused_at = None

        await self._play_station(room.guild)
        if self.station_number is None:
            return "Nothing to play yet. Grind something."
        return "Playing."

    # -- the card banner -----------------------------------------------------------------
    async def _show_live_banner(self, ctx, heard: int, room) -> None:
        if ctx.message is None:
            return
        embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                               pairs=ctx.named_pairs(), total_secs=ctx.duration,
                               booth_listeners=heard, room_name=room.name)
        try:
            await ctx.message.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def _mark_queued(self, ctx) -> None:
        if ctx.message is None:
            return
        embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                               pairs=ctx.named_pairs(), total_secs=ctx.duration,
                               queued_behind=len(self.queue))
        try:
            await ctx.message.edit(embed=embed)
        except discord.HTTPException:
            pass

    # -- the sign on the door ------------------------------------------------------------
    def total_listeners(self, guild) -> int:
        return sum(self.listeners(r) for r in self.rooms(guild))

    def busiest_room(self, guild):
        rooms = sorted(self.rooms(guild), key=self.listeners, reverse=True)
        return rooms[0] if rooms and self.listeners(rooms[0]) else None

    async def refresh_status(self, guild: discord.Guild | None) -> None:
        """Keep ONE message current rather than posting a new one. A channel that fills with
        'the booth is live' notices is worse than no notice at all."""
        if guild is None or not CFG.grinder_channel_id:
            return
        channel = guild.get_channel(CFG.grinder_channel_id)
        if channel is None:
            return
        heard = self.total_listeners(guild)
        if heard >= LIVE_THRESHOLD:
            embed = ui.booth_live_embed(listeners=heard,
                                        grinds_this_session=self.grinds_this_session,
                                        last_up=self.last_up)
        else:
            embed = ui.booth_quiet_embed()
            if heard == 0:
                self.grinds_this_session = 0     # a new session starts when the room refills
                self._arrivals = 0
        try:
            if self.status_message is None:
                self.status_message = await channel.send(embed=embed)
                try:
                    await self.status_message.pin()
                except discord.HTTPException:
                    pass       # pinning is a nicety; the message is useful either way
            else:
                await self.status_message.edit(embed=embed)
        except discord.HTTPException:
            log.warning("booth: could not update the status message", exc_info=True)

    async def on_voice_state_update(self, member, before, after) -> None:
        """Arrivals and departures. Also the only thing that makes the sign change."""
        if member.bot:
            return
        was_in = self.is_a_room(before.channel)
        now_in = self.is_a_room(after.channel)
        if was_in == now_in:
            return

        guild = member.guild
        now = datetime.now(timezone.utc).isoformat()

        if now_in:
            self._record_arrival(member, after.channel, now)
            self._arrivals += 1
            if self._should_announce():
                await self._announce_arrival(guild, member, after.channel)
        else:
            self._record_departure(member, before.channel, now)

        await self.refresh_status(guild)

        if not now_in and self.total_listeners(guild) == 0:
            await self._room_empty(guild)
            return

        # SOMEBODY ARRIVED TO A QUIET ROOM. Before 2026-08-12 they would sit in silence until
        # somebody happened to grind - the single most common way a listening room felt broken.
        if now_in and self.now_playing is None and self.station_number is None:
            await self._play_station(guild)

    # -- listening data ------------------------------------------------------------------------
    # The two gaps recorded as blocking the community phase: do people actually listen, and when
    # do they drop off. Recording is best-effort by design - a database hiccup must never stop
    # somebody joining a room or hearing music.

    def _record_arrival(self, member, room, when: str) -> None:
        try:
            playing = self.now_playing.number if self.now_playing is not None else self.station_number
            store.room_arrival(
                guild_id=getattr(member.guild, "id", None), room_id=room.id, room_name=room.name,
                user_id=member.id, user_name=getattr(member, "display_name", ""), when=when,
                playing_number=playing)
        except Exception:  # noqa: BLE001
            log.warning("booth: could not record an arrival", exc_info=True)

    def _record_departure(self, member, room, when: str) -> None:
        if room is None:
            return
        try:
            store.room_departure(room_id=room.id, user_id=member.id, when=when,
                                 seconds=self._session_seconds(member.id, room.id, when))
        except Exception:  # noqa: BLE001
            log.warning("booth: could not record a departure", exc_info=True)

    @staticmethod
    def _session_seconds(user_id: int, room_id: int, when: str) -> float | None:
        """How long they stayed. Computed here rather than in SQL so the store stays a plain
        table and the clock stays in one place."""
        try:
            row = store.open_session(user_id=user_id, room_id=room_id)
            if row is None:
                return None
            joined = datetime.fromisoformat(row["joined_at"])
            return max(0.0, (datetime.fromisoformat(when) - joined).total_seconds())
        except Exception:  # noqa: BLE001
            return None

    def _should_announce(self) -> bool:
        return self._arrivals <= ANNOUNCE_FIRST or self._arrivals % ANNOUNCE_EVERY == 0

    async def _announce_arrival(self, guild, member, room) -> None:
        if not CFG.grinder_channel_id:
            return
        channel = guild.get_channel(CFG.grinder_channel_id)
        if channel is None:
            return
        try:
            await channel.send(ui.arrival_line(member.display_name, room.name,
                                               self.listeners(room)))
        except discord.HTTPException:
            pass

    async def _room_empty(self, guild) -> None:
        """Nobody left to hear it. Stop and get out - the bot must never sit connected and silent.

        This also ends the station: playing to an empty room burns CPU and a voice connection for
        an audience of nobody. `_station_paused` is cleared too, so the next person to walk in
        gets music rather than inheriting somebody's earlier /stop."""
        self.queue.clear()
        self.now_playing = None
        self.station_number = None
        self._station_paused = False
        vc = guild.voice_client if guild else None
        if vc is not None:
            log.info("booth: room empty, disconnecting")
            try:
                await vc.disconnect(force=True)
            except Exception:  # noqa: BLE001
                log.warning("booth: could not disconnect cleanly", exc_info=True)


    def check_config(self, guild) -> list[str]:
        """Complain loudly at startup if a configured channel is not there any more.

        THE FAILURE THIS PREVENTS, observed 2026-08-11: the founder deleted the voice channel and
        made a new one. The id in the config stopped matching anything, so `is_in_booth` answered
        "no" for everybody and the bot quietly never joined a call. Nothing in the log, nothing on
        a card, no error - just a feature that had silently stopped existing.

        Renaming is fine: an id survives a rename, which is why the text channels kept working.
        Delete-and-recreate is what breaks it.

        Deliberately does NOT guess a replacement, even when there is exactly one obvious candidate.
        A bot that quietly picks a different room to play music in is worse than one that says it
        cannot find the room. It names the candidates so the fix is obvious, and stops there.
        """
        problems: list[str] = []
        if not CFG.rooms_category_id:
            problems.append("GRINDER_ROOMS_CATEGORY_ID is not set, so nothing will ever play out loud")
        elif not self.rooms(guild):
            names = ", ".join(f"{c.name} ({c.id})" for c in getattr(guild, "voice_channels", []))
            problems.append(
                f"GRINDER_ROOMS_CATEGORY_ID={CFG.rooms_category_id} holds no voice channels. "
                f"Voice channels that DO exist: {names or 'none'}")
        if not CFG.grind_category_id:
            problems.append("GRINDER_GRIND_CATEGORY_ID is not set, so /grind is allowed anywhere")
        for key, cid in (("GRINDER_MAIN_CHANNEL_ID", CFG.grinder_channel_id),
                         ("GRINDER_SHOWCASE_CHANNEL_ID", CFG.fresh_grinds_channel_id)):
            if not cid:
                problems.append(f"{key} is not set, so that feature does nothing")
            elif guild.get_channel(cid) is None:
                names = ", ".join(f"#{c.name} ({c.id})" for c in getattr(guild, "text_channels", []))
                problems.append(f"{key}={cid} does not exist any more. Text channels: {names or 'none'}")
        for p in problems:
            log.warning("CONFIG: %s", p)
        return problems


booth = Booth()
