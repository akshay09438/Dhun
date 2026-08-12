"""Two listening rooms with sound at the same time - the whole point of the second identity.

WHAT THIS IS PROVING. Before this, Bollywood_House and Hollywood_Blends shared one voice: whichever
room the bot was standing in had music and the other had silence, and when a grind from the other
room came up the bot WALKED OUT mid-night to serve it. Every test here is a thing that was
impossible with one identity.

THE DOUBLES ARE DELIBERATELY SPLIT IN TWO. Each identity is a separate login with its OWN view of
the server: its own guild object, its own channel objects, its own voice connection. That is not
test decoration - it is exactly the shape of the bug this feature can have. `play_in` reaches for
`channel.guild.voice_client`, so an implementation that reused the main bot's channel object would
quietly play BOTH rooms through ONE connection and look perfectly healthy in the log. The split
doubles are what catch that: the two rooms' connections are different objects, and the tests assert
one is untouched while the other moves.

STILL CANNOT PROVE: that audio comes out. A fake voice client is always more forgiving than
Discord - seven bugs shipped past a green suite on 2026-08-11 that way. That needs a real room, a
real second token, and a real ear.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import booth as booth_mod  # noqa: E402
import speakers  # noqa: E402
import store  # noqa: E402
import voices as voices_mod  # noqa: E402

ROOMS_CAT = 999
A_ID, B_ID = 10, 20


class FakeVC:
    def __init__(self):
        self.playing = True
        self.stops = 0
        self.disconnected = False

    def is_playing(self):
        return self.playing

    def stop(self):
        self.stops += 1
        self.playing = False

    async def disconnect(self, force=False):
        self.disconnected = True


class FakeGuild:
    """One identity's view of the server. Its `voice_client` is THAT identity's connection."""

    def __init__(self, name):
        self.id = 1
        self.name = name
        self.voice_channels = []
        self.voice_client = None

    def get_channel(self, _id):
        return None


class FakeChannel:
    def __init__(self, cid, name, guild, members=()):
        self.id = cid
        self.name = name
        self.guild = guild
        self.members = list(members)
        self.category = type("Cat", (), {"id": ROOMS_CAT})()

    def connect(self):      # marks this as a voice channel for is_a_room
        raise AssertionError("tests must never really connect")


class FakeMember:
    def __init__(self, uid, guild, channel=None, bot=False):
        self.id = uid
        self.display_name = f"user{uid}"
        self.guild = guild
        self.bot = bot
        self.voice = type("VS", (), {"channel": channel})()


class SpeakerClient:
    """An extra identity's login: it sees its OWN copies of the channels."""

    def __init__(self, channels):
        self._by_id = {c.id: c for c in channels}

    def get_channel(self, cid):
        return self._by_id.get(cid)


class Server:
    """The same two rooms, as seen by two different identities."""

    def __init__(self, extras=1, speaker_sees=(A_ID, B_ID)):
        self.main_guild = FakeGuild("as the main Grinder sees it")
        self.main_guild.voice_client = FakeVC()
        self.a = FakeChannel(A_ID, "Bollywood_House", self.main_guild)
        self.b = FakeChannel(B_ID, "Hollywood_Blends", self.main_guild)
        self.main_guild.voice_channels = [self.a, self.b]

        self.spk_guild = FakeGuild("as the extra voice sees it")
        self.spk_guild.voice_client = FakeVC()
        spk_channels = [FakeChannel(cid, n, self.spk_guild) for cid, n in
                        ((A_ID, "Bollywood_House"), (B_ID, "Hollywood_Blends"))
                        if cid in speaker_sees]
        self.spk_a = next((c for c in spk_channels if c.id == A_ID), None)
        self.spk_b = next((c for c in spk_channels if c.id == B_ID), None)

        pool = speakers.SpeakerPool([f"tok-{i}" for i in range(extras)])
        for s in pool.speakers:
            s.client = SpeakerClient(spk_channels)
        self.booth = booth_mod.Booth(voicebox=voices_mod.VoiceBox(pool))

    def sit(self, uid, room):
        """Put somebody in a room - in the MAIN client's copy, which is what Discord hands us."""
        m = FakeMember(uid, self.main_guild, channel=room)
        room.members.append(m)
        return m


class Ctx:
    def __init__(self, number, member):
        self.number = number
        self.message = None
        self.audio_path = f"grind{number}.wav"
        self.duration = 10.0
        self.interaction = type("I", (), {"user": member, "guild": member.guild})()

    def named_pairs(self):
        return [("A", "B")]

    def label(self):
        return f"grind {self.number}"


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path):
    monkeypatch.setattr(booth_mod.CFG, "rooms_category_id", ROOMS_CAT, raising=False)
    monkeypatch.setattr(booth_mod.CFG, "grinder_channel_id", None, raising=False)
    monkeypatch.setattr(booth_mod.CFG, "fresh_grinds_channel_id", None, raising=False)
    store.reset_for_tests(tmp_path / "grinder.db")
    yield


@pytest.fixture
def plays(monkeypatch):
    """Everything that reached the audio player, as (which identity's channel, file, offset)."""
    got = []

    async def fake_play_in(channel, path, on_finished=None, start_at=0.0):
        got.append((channel, Path(str(path)).stem, start_at))

    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)
    return got


# --- the thing that was impossible ------------------------------------------------------------
def test_two_rooms_play_at_the_same_time(plays):
    """THE WHOLE FEATURE. Before this, the second grind waited three minutes for the first room to
    finish, and its room sat in silence the entire time."""
    s = Server(extras=1)
    ana = s.sit(1, s.a)
    ben = s.sit(2, s.b)

    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))

    assert [p[1] for p in plays] == ["grind1", "grind2"], "both must have played"
    assert s.booth.queue == [], "neither should be waiting"


def test_each_room_plays_through_its_own_connection(plays):
    """The bug this exists to catch: reusing the main bot's channel object would send BOTH rooms
    through ONE connection, which sounds exactly like the problem being fixed and looks fine in the
    log."""
    s = Server(extras=1)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, s.sit(1, s.a))))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, s.sit(2, s.b))))

    first_channel, second_channel = plays[0][0], plays[1][0]
    assert first_channel is s.a, "room A goes through the main Grinder's own copy of the room"
    assert second_channel is s.spk_b, "room B goes through the EXTRA identity's own copy"
    assert first_channel.guild is not second_channel.guild, "two identities, two connections"


def test_the_second_room_does_not_drag_the_bot_out_of_the_first(plays):
    """The old behaviour, stated as a test so it can never come back: serving room B used to MOVE
    the single connection, so room A went silent with people still sitting in it."""
    s = Server(extras=1)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, s.sit(1, s.a))))
    before = s.main_guild.voice_client.stops
    asyncio.run(s.booth.on_grind_finished(Ctx(2, s.sit(2, s.b))))
    assert s.main_guild.voice_client.stops == before, "room A's audio must not be touched"


def test_a_third_room_with_only_two_voices_waits_and_is_told_so(plays):
    """Rooms are free; identities are not. When they run out the person must be told where they
    are, not left staring at 'grinding...' assuming it broke."""
    s = Server(extras=1)
    c = FakeChannel(30, "Third_Room", s.main_guild)
    s.main_guild.voice_channels.append(c)

    asyncio.run(s.booth.on_grind_finished(Ctx(1, s.sit(1, s.a))))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, s.sit(2, s.b))))
    asyncio.run(s.booth.on_grind_finished(Ctx(3, s.sit(3, c))))

    assert [p[1] for p in plays] == ["grind1", "grind2"]
    assert [x.number for x in s.booth.queue] == [3], "the third waits rather than cutting anyone off"
    assert "all busy" in s.booth.every_voice_busy_line()


# --- the controls stay inside their own room -----------------------------------------------------
def test_skipping_in_one_room_does_not_move_the_other(plays):
    """A /skip in Hollywood_Blends reaching into Bollywood_House would be the most obvious possible
    way for two rooms to feel broken."""
    s = Server(extras=1)
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))

    deck_a, deck_b = s.booth.deck(s.a), s.booth.deck(s.b)
    deck_a._mark_playing("a.wav", seams=[100.0, 200.0])
    deck_b._mark_playing("b.wav", seams=[50.0, 150.0])
    a_before = (deck_a._now_path, deck_a._now_offset, deck_a._play_token)

    msg = asyncio.run(s.booth.skip(ben))

    assert "track 2" in msg
    assert plays[-1][2] == 50.0, "room B seeks to ITS next boundary"
    assert (deck_a._now_path, deck_a._now_offset, deck_a._play_token) == a_before, \
        "room A's position must not have moved"
    assert s.main_guild.voice_client.stops == 0


def test_stopping_one_room_leaves_the_other_playing(plays):
    s = Server(extras=1)
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))
    deck_a, deck_b = s.booth.deck(s.a), s.booth.deck(s.b)

    asyncio.run(s.booth.stop_playback(ben))

    assert deck_b._station_paused is True
    assert deck_a._station_paused is False, "room A never asked for quiet"
    assert deck_a.now_playing is not None, "room A is still playing"
    assert s.spk_guild.voice_client.stops == 1, "only the extra identity's audio was stopped"
    assert s.main_guild.voice_client.stops == 0, "the main Grinder's audio was not touched"


def test_one_room_is_never_handed_two_identities(plays):
    """Two identities in one room would play two different grinds over each other - worse than
    silence."""
    s = Server(extras=2)
    ana = s.sit(1, s.a)
    for n in range(1, 4):
        asyncio.run(s.booth.on_grind_finished(Ctx(n, ana)))
    holders = [v for v in s.booth.voices.all_voices if v.room_id == A_ID]
    assert len(holders) == 1


# --- when it is only the main bot, nothing changed -------------------------------------------------
def test_with_no_extra_token_the_second_room_still_waits(plays):
    """THE REGRESSION THAT MATTERS MOST. Until the founder pastes a token, every single thing must
    behave exactly as it did before this feature existed."""
    s = Server(extras=0)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, s.sit(1, s.a))))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, s.sit(2, s.b))))
    assert [p[1] for p in plays] == ["grind1"]
    assert [x.number for x in s.booth.queue] == [2]


def test_with_no_extra_token_the_one_voice_still_moves_on_when_a_room_finishes(plays):
    """The other half of today's behaviour: the single identity hands over to whoever is next in
    line, even when they are in a different room. Without this the second room would wait forever."""
    s = Server(extras=0)
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))

    asyncio.run(s.booth.deck(s.a).advance())          # room A's track ends

    assert [p[1] for p in plays] == ["grind1", "grind2"]
    assert s.booth.queue == []
    assert s.booth.voices.holder_of(B_ID) is not None
    assert s.booth.voices.holder_of(A_ID) is None, "room A let the identity go"


def test_a_waiting_grind_outranks_a_replay_in_another_room(plays, tmp_path):
    """A fresh grind ANYWHERE beats a repeat ANYWHERE - the same rule that already lets a new grind
    interrupt the station in its own room. Otherwise room A would start replaying old mixes while
    room B's brand-new one sat waiting for a voice."""
    s = Server(extras=0)
    audio = tmp_path / "old.wav"
    audio.write_bytes(b"RIFF")
    n = store.new_grind(user_id=9, user_name="x", pairs=[["b", "v", "B", "V"]], created_at="t")
    store.set_audio_path(n, str(audio))

    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))
    asyncio.run(s.booth.deck(s.a).advance())

    assert [p[1] for p in plays] == ["grind1", "grind2"]
    assert "old" not in [p[1] for p in plays], "a replay must not jump the queue"


# --- an identity that cannot do its job ------------------------------------------------------------
def test_an_identity_that_cannot_see_the_room_does_not_swallow_it(plays):
    """BY FAR the likeliest real-world misconfiguration: the second bot was invited to the server
    but never given View Channel / Connect on the rooms category. It must hand the voice straight
    back rather than holding a room it cannot enter."""
    s = Server(extras=1, speaker_sees=(A_ID,))       # the extra cannot see room B
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))

    assert [p[1] for p in plays] == ["grind1"]
    assert [x.number for x in s.booth.queue] == [2], "it waits, exactly as if no voice were free"
    assert all(v.room_id != B_ID for v in s.booth.voices.all_voices), \
        "the voice must not be left holding a room it cannot enter"


# --- the grace period when a room empties -----------------------------------------------------------
def test_a_room_that_empties_holds_its_voice_for_a_moment(plays, monkeypatch):
    """Founder decision: stepping out for twenty seconds must not kill the music you were
    listening to. It is a HOLD, not a stop-and-restart."""
    s = Server(extras=1)
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))
    deck_a = s.booth.deck(s.a)

    s.a.members.remove(ana)                          # everybody walks out of room A
    ana.voice = type("VS", (), {"channel": None})()
    asyncio.run(s.booth.on_voice_state_update(
        ana, type("B", (), {"channel": s.a})(), type("A", (), {"channel": None})()))

    assert deck_a.empty_since is not None, "the timer started"
    assert s.booth.voices.holder_of(A_ID) is not None, "but the voice is still held"
    assert deck_a.now_playing is not None, "and the music never stopped"


def test_coming_back_inside_the_grace_period_keeps_the_music(plays):
    s = Server(extras=1)
    ana = s.sit(1, s.a)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    deck_a = s.booth.deck(s.a)
    deck_a.empty_since = 1.0                          # pretend the room emptied a moment ago

    kept = asyncio.run(s.booth.release_if_still_empty(s.main_guild, A_ID))

    assert kept is False, "somebody is in there; nothing may be let go of"
    assert deck_a.empty_since is None, "the timer is forgotten"
    assert s.booth.voices.holder_of(A_ID) is not None
    assert deck_a.now_playing is not None, "a hold, not a stop-and-restart"


def test_a_room_still_empty_after_the_grace_period_lets_its_voice_go(plays):
    s = Server(extras=1)
    ana = s.sit(1, s.a)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    deck_a = s.booth.deck(s.a)
    s.a.members.remove(ana)                           # really empty now
    deck_a.empty_since = 1.0

    released = asyncio.run(s.booth.release_if_still_empty(s.main_guild, A_ID))

    assert released is True
    assert s.booth.voices.holder_of(A_ID) is None, "another room can have it now"
    assert deck_a.now_playing is None
    assert s.main_guild.voice_client.disconnected is True, "no identity sits connected and silent"


def test_the_freed_voice_can_immediately_serve_another_room(plays):
    """The point of releasing at all. With one identity, room B gets sound the moment room A is
    genuinely done with it."""
    s = Server(extras=0)
    ana, ben = s.sit(1, s.a), s.sit(2, s.b)
    asyncio.run(s.booth.on_grind_finished(Ctx(1, ana)))
    s.a.members.remove(ana)
    s.booth.deck(s.a).empty_since = 1.0
    asyncio.run(s.booth.release_if_still_empty(s.main_guild, A_ID))

    asyncio.run(s.booth.on_grind_finished(Ctx(2, ben)))
    assert [p[1] for p in plays] == ["grind1", "grind2"]
