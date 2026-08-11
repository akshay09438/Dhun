"""The Booth - the one room where grinds play out loud, and the sign on the door.

The problem this solves: voice was invisible. Someone saw a channel with a speaker icon, had no
way to tell whether anything was happening, so they never joined, so nothing ever happened. Two
fixes live here.

1. A grind made by somebody sitting in The Booth plays there automatically. No button. Everyone in
   the room hears it at the same second, which is the entire product - shared surprise.
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

    # -- the room ------------------------------------------------------------------------
    def channel(self, guild: discord.Guild | None):
        """The configured room, or None.

        Checked by CAPABILITY rather than by class: what matters is that the id points at
        something we can join and that has people in it. A text channel has `.members` but no
        `.connect`, so a mis-set id is caught here with a clear None instead of blowing up later
        inside playback, where the error would read as "voice is broken".
        """
        if guild is None or not CFG.booth_channel_id:
            return None
        ch = guild.get_channel(CFG.booth_channel_id)
        if ch is None or not hasattr(ch, "connect") or not hasattr(ch, "members"):
            return None
        return ch

    def listeners(self, guild: discord.Guild | None) -> int:
        """People in the room, not counting Grinder itself - the bot is not an audience."""
        ch = self.channel(guild)
        return len([m for m in ch.members if not m.bot]) if ch else 0

    def is_in_booth(self, member) -> bool:
        state = getattr(member, "voice", None)
        if state is None or state.channel is None:
            return False
        return bool(CFG.booth_channel_id) and state.channel.id == CFG.booth_channel_id

    # -- playing -------------------------------------------------------------------------
    async def on_grind_finished(self, ctx) -> None:
        """Called when a grind's audio is ready. Plays it out loud only if its owner is actually
        sitting in The Booth - a grind made from a text channel by someone who is not in the room
        is a private thing and must not seize the speakers."""
        member = ctx.interaction.user
        if not self.is_in_booth(member) or ctx.audio_path is None:
            return
        async with self._lock:
            if self.now_playing is not None:
                self.queue.append(ctx)
                await self._mark_queued(ctx)
                log.info("booth: grind #%s queued behind %s (%d waiting)",
                         ctx.number, self.now_playing.number, len(self.queue))
                return
        await self._play(ctx)

    async def _play(self, ctx) -> None:
        guild = ctx.interaction.guild
        channel = self.channel(guild)
        if channel is None:
            log.warning("booth: no voice channel configured; not playing grind #%s", ctx.number)
            return
        self.now_playing = ctx
        self.grinds_this_session += 1
        self.last_up = ctx.label()
        heard = self.listeners(guild)
        log.info("booth: playing grind #%s (%s) to %d listening", ctx.number, ctx.label(), heard)

        await self._show_live_banner(ctx, heard)
        await self.refresh_status(guild)
        try:
            await voice_player.play_in(channel, ctx.audio_path, on_finished=self._advance)
        except Exception:  # noqa: BLE001 - the room going quiet must never kill the bot
            log.exception("booth: playback failed for grind #%s", ctx.number)
            await self._advance()

    async def _advance(self) -> None:
        """One finished, take the next. Called back from the audio player."""
        async with self._lock:
            self.now_playing = None
            nxt = self.queue.pop(0) if self.queue else None
        if nxt is not None:
            await self._play(nxt)

    # -- the card banner -----------------------------------------------------------------
    async def _show_live_banner(self, ctx, heard: int) -> None:
        if ctx.message is None:
            return
        embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                               pairs=ctx.named_pairs(), total_secs=ctx.duration,
                               booth_listeners=heard)
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
    async def refresh_status(self, guild: discord.Guild | None) -> None:
        """Keep ONE message current rather than posting a new one. A channel that fills with
        'the booth is live' notices is worse than no notice at all."""
        if guild is None or not CFG.grinder_channel_id:
            return
        channel = guild.get_channel(CFG.grinder_channel_id)
        if channel is None:
            return
        heard = self.listeners(guild)
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
        was_in = bool(before.channel and CFG.booth_channel_id
                      and before.channel.id == CFG.booth_channel_id)
        now_in = bool(after.channel and CFG.booth_channel_id
                      and after.channel.id == CFG.booth_channel_id)
        if was_in == now_in:
            return

        guild = member.guild
        if now_in:
            self._arrivals += 1
            if self._should_announce():
                await self._announce_arrival(guild, member)
        await self.refresh_status(guild)

        if not now_in and self.listeners(guild) == 0:
            await self._room_empty(guild)

    def _should_announce(self) -> bool:
        return self._arrivals <= ANNOUNCE_FIRST or self._arrivals % ANNOUNCE_EVERY == 0

    async def _announce_arrival(self, guild, member) -> None:
        if not CFG.grinder_channel_id:
            return
        channel = guild.get_channel(CFG.grinder_channel_id)
        if channel is None:
            return
        try:
            await channel.send(ui.arrival_line(member.display_name, self.listeners(guild)))
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


booth = Booth()
