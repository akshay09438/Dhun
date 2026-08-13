"""The listening rooms - where grinds play out loud, and the sign on the door.

The problem this solves: voice was invisible. Someone saw a channel with a speaker icon, had no
way to tell whether anything was happening, so they never joined, so nothing ever happened. Two
fixes live here.

1. A grind made by somebody sitting in one of the rooms plays THERE automatically. No button.
   Everyone in that room hears it at the same second, which is the entire product - shared surprise.
2. A single pinned message in the grind channel that always says whether the room is live, so the
   answer to "is anything happening" is visible from the text channel.

ONE GRIND AT A TIME, PER ROOM (founder decision 2026-08-11). A second grind finished while one is
playing in that room waits its turn rather than cutting in. A room where the music restarts every
ninety seconds is worse than a room with a short queue.

MORE THAN ONE ROOM AT A TIME (2026-08-12). This class used to hold ONE of everything - one thing
playing, one waiting list, one position, one station - because a Discord bot holds exactly one voice
connection per SERVER and so only one room could ever have sound. Worse than that: when a grind made
in a second room reached the front of the queue, the bot WALKED OUT of the room it was in, leaving
those people in silence, to serve one person next door.

It is now a coordinator: one `Deck` per room (see deck.py), one `VoiceBox` of identities that rooms
borrow (see voices.py), and the rules for who gets a voice when. WITH NO EXTRA TOKENS CONFIGURED
THERE IS EXACTLY ONE VOICE AND EVERY DECISION BELOW COLLAPSES TO WHAT THIS FILE DID BEFORE - that is
the property the regression tests hold us to, and it is why nothing changes for the founder until
they choose to paste a second token.

HONESTY NOTE: none of the behaviour in this file can be proven by a test. A fake voice client will
always be more forgiving than Discord (that is exactly how seven bugs shipped past a green suite on
2026-08-11). The unit tests cover the decisions - who plays next, who gets a voice, when to sleep,
what the sign says - and the real playback needs a real room.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord

import store
import ui
import voice_player  # noqa: F401 - re-exported so tests can monkeypatch booth.voice_player
import voices as voices_mod
from botconfig import load_config
from deck import Deck

log = logging.getLogger("promptdj.discord")
CFG = load_config()

# How many people must be in the room before the sign says LIVE. One person in a room is not a
# session; two is. Configurable because it is a taste call, not a fact.
LIVE_THRESHOLD = 2

# ARRIVAL NOTES ARE GONE (founder decision 2026-08-13): "no notification should go when a person or
# any individual joins a Bollywood house or a Hollywood house, because people can automatically see
# people in their room. I think there is no requirement for the notification."
#
# They were throttled - the first arrival, then every third - but the counter reset every time the
# room emptied, so one person stepping out and back in was announced as if they were the first
# person again. Testing a room a few times filled #get-shit-done with a wall of "walked into" lines.
# Discord's own member list already shows who is in a voice room, so the notice said nothing the
# screen was not already saying.
#
# What is DELIBERATELY KEPT is `_record_arrival` / `_record_departure`: who listened and for how
# long is the drop-off signal, one of the two data gaps recorded as blocking the community phase.
# The announcement and the recording happened in the same moment but are different jobs; only the
# talking is removed.

# How long a room's identity is HELD after everybody walks out (founder decision 2026-08-12).
# Stepping out for twenty seconds must not kill the music you were listening to. The cost, accepted
# knowingly: for up to a minute a seat is held by an empty room, so another room could be briefly
# silent. It is a HOLD, not a stop-and-restart - somebody returning inside the window finds the
# music still playing.
EMPTY_ROOM_GRACE_SECS = 60.0


class Booth:
    """The coordinator. Owns the decks, the identities, and everything that is server-wide."""

    def __init__(self, voicebox=None) -> None:
        self.queue: list = []                       # GrindContexts waiting, oldest first
        self.decks: dict[int, Deck] = {}            # room id -> that room's playback
        self.voices = voicebox if voicebox is not None else voices_mod.VoiceBox()
        self.grinds_this_session = 0
        self.last_up: str | None = None
        self.status_message: discord.Message | None = None
        self.lock = asyncio.Lock()
        self.last_guild = None       # so a deck still knows the server when the STATION ends
        # Looks up a set's track boundaries from the engine, given its set id. Injected by bot.py so
        # the booth needs no HTTP client of its own and stays unit-testable. None = no lookup.
        self.seam_lookup = None

    # -- the decks -------------------------------------------------------------------------------
    def deck(self, room) -> Deck:
        """This room's playback, created the first time the room is used."""
        return self.deck_by_id(getattr(room, "id", room))

    def deck_by_id(self, room_id: int) -> Deck:
        if room_id not in self.decks:
            self.decks[room_id] = Deck(room_id, self)
        return self.decks[room_id]

    def remember_guild(self, guild) -> None:
        if guild is not None:
            self.last_guild = guild

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

    def room_by_id(self, guild, room_id: int):
        for room in self.rooms(guild):
            if room.id == room_id:
                return room
        return None

    def listeners(self, channel) -> int:
        """People in one room, not counting Grinder itself - the bot is not an audience."""
        if channel is None:
            return 0
        return len([m for m in channel.members if not m.bot])

    # -- who gets a voice --------------------------------------------------------------------
    def voices_all_busy(self) -> bool:
        return all(not v.free for v in self.voices.all_voices)

    def every_voice_busy_line(self) -> str:
        """Said out loud when there is genuinely no identity left to give. Never a shrug: a person
        told 'waiting' will wait, a person told nothing assumes it broke and presses again."""
        n = self.voices.rooms_with_sound
        # Say WHO holds WHAT at the moment of refusal. The founder hit a refusal saying "one room"
        # ten minutes after the startup log had said two, and nothing recorded enough to tell which
        # of them was wrong. A refusal that cannot be explained afterwards is a refusal that gets
        # guessed at.
        log.warning("booth: refusing - the box holds %d identities (%s)", n,
                    ", ".join(f"{v.label} -> room {v.room_id}" for v in self.voices.all_voices))
        rooms = "one room" if n == 1 else f"{n} rooms"
        return (f"Grinder can only have sound in {rooms} at once, and they are all busy. "
                "This room gets music the moment one frees up.")

    def _ahead_of(self, room_id: int) -> int:
        """How many grinds are already waiting for THIS room. That is what decides someone's wait -
        a queue in the other room does not delay them at all."""
        n = 0
        for c in self.queue:
            room = self.room_of(getattr(getattr(c, "interaction", None), "user", None))
            if room is not None and room.id == room_id:
                n += 1
        return n

    def take_next_for(self, room_id: int):
        """The oldest waiting grind whose owner is sitting in this room, if any. Called under the
        lock. The owner's room is re-read NOW rather than remembered, because people move."""
        for i, c in enumerate(self.queue):
            room = self.room_of(getattr(getattr(c, "interaction", None), "user", None))
            if room is not None and room.id == room_id:
                return self.queue.pop(i)
        return None

    async def wait_for_a_voice(self, ctx, room) -> None:
        """No identity free. Queue it and SAY so - this is the one place the app admits out loud
        that voices are finite, and it is much better than a person staring at 'grinding...'."""
        async with self.lock:
            ahead = self._ahead_of(room.id)
            self.queue.append(ctx)
        log.info("booth: grind #%s waits for a free voice in %s (%d ahead in that room)",
                 ctx.number, getattr(room, "name", room.id), ahead)
        await self._mark_queued(ctx, ahead=ahead, waiting_for_voice=True)

    async def hand_over_if_someone_is_waiting(self, deck) -> bool:
        """This room has nothing more of its own. If ANOTHER room has a real grind waiting with no
        identity to play it, give this one up rather than starting a repeat.

        A FRESH GRIND ANYWHERE OUTRANKS A REPEAT ANYWHERE - the same rule that already lets a new
        grind interrupt the station in its own room. With only the main bot configured this IS
        today's behaviour: the single voice moves on to whoever is next in line."""
        taken = None
        async with self.lock:
            for i, c in enumerate(self.queue):
                room = self.room_of(getattr(getattr(c, "interaction", None), "user", None))
                if room is None or room.id == deck.room_id:
                    continue
                if self.voices.holder_of(room.id) is not None:
                    continue                     # that room already has a voice; it is not stuck
                taken = self.queue.pop(i)
                break
        if taken is None:
            return False
        deck.go_quiet()
        await deck.release_voice()
        await self.start(taken)
        return True

    # -- playing -------------------------------------------------------------------------
    async def start(self, ctx) -> None:
        """Put one grind on air in whichever room its owner is sitting in RIGHT NOW."""
        room = self.room_of(getattr(getattr(ctx, "interaction", None), "user", None))
        if room is None:
            log.info("booth: grind #%s not played, its owner left the rooms", ctx.number)
            return
        await self.deck(room).play_grind(ctx, room)

    async def on_grind_finished(self, ctx) -> None:
        """Called when a grind's audio is ready. Plays it out loud only if its owner is sitting in
        one of the rooms - a grind made from a text channel by someone who is not in a room is a
        private thing and must not seize anybody's speakers."""
        room = self.room_of(ctx.interaction.user)
        if room is None or ctx.audio_path is None:
            return
        deck = self.deck(room)

        async with self.lock:
            if deck.now_playing is not None:
                ahead = self._ahead_of(room.id)
                self.queue.append(ctx)
                await self._mark_queued(ctx, ahead=ahead + 1)
                log.info("booth: grind #%s queued behind #%s in %s (%d waiting there)",
                         ctx.number, deck.now_playing.number, getattr(room, "name", room.id),
                         ahead + 1)
                return

        await deck.play_grind(ctx, room)

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

    # -- controls ------------------------------------------------------------------------------
    # Each of these acts on the caller's OWN room and cannot reach any other. Skipping in
    # Hollywood_Blends must not move Bollywood_House's track, and it has no way to name it.

    async def skip(self, member) -> str:
        """Next track. Inside a set that means the NEXT MEMBER of the set, not abandoning all five.

        ANYONE IN THE ROOM MAY SKIP (founder decision 2026-08-12). Deliberately not owner-only: a
        bad mix whose owner has wandered off would otherwise hold the room for three minutes. At
        this scale social pressure handles abuse better than a vote does."""
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then skip."
        return await self.deck(room).skip(room)

    async def stop_playback(self, member) -> str:
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then stop."
        return await self.deck(room).stop(room)

    async def play(self, member) -> str:
        """Start the music in the room this person is sitting in - and bring a Grinder in if one is
        not already there.

        This is the command that was missing: before it, the ONLY way to get Grinder into a room was
        to finish a grind while sitting in one."""
        room = self.room_of(member)
        if room is None:
            return "Join a listening room first, then play."
        self.remember_guild(getattr(room, "guild", None))
        return await self.deck(room).resume(room)

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

    async def _mark_queued(self, ctx, ahead: int = 0, waiting_for_voice: bool = False) -> None:
        if ctx.message is None:
            return
        embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                               pairs=ctx.named_pairs(), total_secs=ctx.duration,
                               queued_behind=max(ahead, 1),
                               waiting_for_voice=waiting_for_voice)
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
        self.remember_guild(guild)
        now = datetime.now(timezone.utc).isoformat()

        if now_in:
            # Recorded, never announced. Arriving in a room posts NOTHING anywhere.
            self._record_arrival(member, after.channel, now)
        else:
            self._record_departure(member, before.channel, now)

        await self.refresh_status(guild)

        if not now_in and self.total_listeners(guild) == 0:
            await self._room_empty(guild)
            return

        # THAT ROOM emptied but others have not. Hold its identity for a moment rather than
        # snatching it away - stepping out for twenty seconds must not kill the music.
        if not now_in and before.channel is not None and self.listeners(before.channel) == 0:
            self._start_grace(guild, before.channel)

        # ARRIVING STARTS NOTHING (founder decision, 2026-08-12, after listening to it). Walking in
        # used to put a past mix on automatically. It was built to stop rooms feeling dead; used for
        # real it meant music appearing that nobody had asked for. All that happens now is that
        # coming back cancels the empty-room timer, so somebody who stepped out finds their music
        # still playing.
        if now_in:
            self.deck(after.channel).empty_since = None

    # -- the grace period ---------------------------------------------------------------------
    def _start_grace(self, guild, room) -> None:
        deck = self.deck(room)
        deck.empty_since = time.monotonic()
        log.info("booth: %s is empty, holding its voice for %.0fs",
                 getattr(room, "name", room.id), EMPTY_ROOM_GRACE_SECS)
        try:
            asyncio.get_running_loop().create_task(self._release_after_grace(guild, room.id))
        except RuntimeError:  # pragma: no cover - no loop running (only in odd test contexts)
            pass

    async def _release_after_grace(self, guild, room_id: int) -> None:
        await asyncio.sleep(EMPTY_ROOM_GRACE_SECS)
        await self.release_if_still_empty(guild, room_id)

    async def release_if_still_empty(self, guild, room_id: int) -> bool:
        """Let go of an empty room's identity, unless somebody came back. Returns True if released.

        A HOLD, NOT A STOP: if they returned inside the window the music never paused, so there is
        nothing to restart - only the timer to forget."""
        deck = self.deck_by_id(room_id)
        room = self.room_by_id(guild, room_id)
        if room is not None and self.listeners(room) > 0:
            deck.empty_since = None
            return False
        if deck.empty_since is None and deck.voice is None:
            return False                     # nothing to let go of
        deck.go_quiet()
        deck.empty_since = None
        await deck.release_voice()           # gives the claim back AND leaves the channel
        log.info("booth: let go of room %s - nobody came back", room_id)
        return True

    # -- listening data ------------------------------------------------------------------------
    # The two gaps recorded as blocking the community phase: do people actually listen, and when
    # do they drop off. Recording is best-effort by design - a database hiccup must never stop
    # somebody joining a room or hearing music.

    def _record_arrival(self, member, room, when: str) -> None:
        try:
            deck = self.deck(room)
            playing = deck.now_playing.number if deck.now_playing is not None else None
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

    async def _room_empty(self, guild) -> None:
        """Nobody left to hear it, anywhere. Stop and get out - no identity may sit connected and
        silent.

        Playing to an empty room burns CPU and a voice connection for an audience of nobody."""
        self.queue.clear()
        for deck in self.decks.values():
            deck.go_quiet()
            deck.empty_since = None
            await deck.release_voice()       # each identity gives back its claim AND leaves
        self.voices.release_all()
        # Belt and braces for an identity that was connected without ever holding a claim - a bot
        # left over from a previous run, say. It costs one call and it is the difference between a
        # clean server and a Grinder sitting silently in an empty room.
        guild_vc = getattr(guild, "voice_client", None)
        if guild_vc is not None:
            log.info("booth: room empty, disconnecting")
            try:
                await guild_vc.disconnect(force=True)
            except Exception:  # noqa: BLE001
                log.warning("booth: could not disconnect cleanly", exc_info=True)

    def check_config(self, guild) -> list[str]:
        """Complain loudly at startup if a configured channel is not there any more.

        THE FAILURE THIS PREVENTS, observed 2026-08-11: the founder deleted the voice channel and
        made a new one. The id in the config stopped matching anything, so the booth answered
        "nobody is in a room" for everybody and the bot quietly never joined a call. Nothing in the
        log, nothing on a card, no error - just a feature that had silently stopped existing.

        Renaming is fine: an id survives a rename, which is why the text channels kept working.
        Delete-and-recreate is what breaks it.

        Deliberately does NOT guess a replacement, even when there is exactly one obvious candidate.
        A bot that quietly picks a different room to play music in is worse than one that says it
        cannot find the room. It names the candidates so the fix is obvious, and stops there."""
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
        # Not a problem, but the single most useful line the founder can see at startup: how many
        # rooms can actually have sound. Discovering that limit from a room that stays quiet all
        # night is how this feature came to be needed in the first place.
        rooms_here = len(self.rooms(guild))
        if rooms_here > self.voices.rooms_with_sound:
            problems.append(
                f"{rooms_here} listening rooms exist but only {self.voices.rooms_with_sound} can "
                f"have sound at once. Add GRINDER_ROOM_TOKENS (one extra bot token per extra room) "
                f"or keep fewer rooms - the others will be silent while one is playing.")
        for p in problems:
            log.warning("CONFIG: %s", p)
        return problems


booth = Booth()
