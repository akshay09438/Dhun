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
import logging

import discord

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
        async with self._lock:
            if self.now_playing is not None:
                self.queue.append(ctx)
                await self._mark_queued(ctx)
                log.info("booth: grind #%s queued behind #%s (%d waiting)",
                         ctx.number, self.now_playing.number, len(self.queue))
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
        """One finished, take the next. Called back from the audio player."""
        async with self._lock:
            self.now_playing = None
            nxt = self.queue.pop(0) if self.queue else None
        if nxt is not None:
            await self._play(nxt)

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
        if now_in:
            self._arrivals += 1
            if self._should_announce():
                await self._announce_arrival(guild, member, after.channel)
        await self.refresh_status(guild)

        if not now_in and self.total_listeners(guild) == 0:
            await self._room_empty(guild)

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
        """Nobody left to hear it. Stop and get out - the bot must never sit connected and silent."""
        self.queue.clear()
        self.now_playing = None
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
