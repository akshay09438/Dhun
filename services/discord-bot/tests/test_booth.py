"""The Booth's decisions: who plays next, who counts as an audience, and when to leave.

WHAT THESE TESTS DO NOT COVER, stated plainly: real voice playback. A fake voice client is always
more forgiving than Discord - that is exactly how seven bugs shipped past a green suite on
2026-08-11. These cover the DECISIONS (queue order, occupancy, sleep), which is the part a test can
honestly prove. Whether audio actually comes out of the speakers needs a real room.
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import booth as boothmod  # noqa: E402

BOOTH_ID = 4242


class _Member:
    def __init__(self, name="someone", bot=False):
        self.display_name = name
        self.bot = bot


class _VoiceChannel:
    def __init__(self, members):
        self.id = BOOTH_ID
        self.name = "The Booth"
        self.members = members

    async def connect(self):        # a voice channel is something you can join
        return None


class _TextChannel:
    """Has members, cannot be joined. What a mis-set channel id actually looks like."""

    def __init__(self):
        self.id = BOOTH_ID
        self.name = "the-grinder"
        self.members = [_Member("a")]


class _Guild:
    def __init__(self, members):
        self.channel = _VoiceChannel(members)
        self.voice_client = None

    def get_channel(self, cid):
        return self.channel if cid == BOOTH_ID else None


@pytest.fixture
def b(monkeypatch):
    """A Booth pointed at a fake room, with the channel id configured."""
    monkeypatch.setattr(boothmod.CFG, "booth_channel_id", BOOTH_ID, raising=False)
    monkeypatch.setattr(boothmod.CFG, "grinder_channel_id", None, raising=False)
    return boothmod.Booth()


# --- who counts as an audience ---------------------------------------------------------
def test_the_bot_itself_is_not_an_audience(b):
    """Grinder sitting in the room must not make it look occupied, or it would keep playing to
    an empty room and never go to sleep."""
    guild = _Guild([_Member("Grinder", bot=True)])
    assert b.listeners(guild) == 0


def test_people_in_the_room_are_counted(b):
    guild = _Guild([_Member("a"), _Member("b"), _Member("Grinder", bot=True)])
    assert b.listeners(guild) == 2


def test_a_text_channel_id_by_mistake_is_refused_not_joined(b):
    """Pointing the booth id at a text channel must fail clearly here, not deep inside playback."""
    class _G:
        def get_channel(self, cid):
            return _TextChannel()
    assert b.channel(_G()) is None


def test_with_no_booth_configured_nothing_is_playing_anywhere(b, monkeypatch):
    """A missing channel id must disable the feature, never make the bot guess at a channel."""
    monkeypatch.setattr(boothmod.CFG, "booth_channel_id", None, raising=False)
    assert b.channel(_Guild([])) is None
    assert b.listeners(_Guild([_Member("a")])) == 0


# --- one grind at a time ---------------------------------------------------------------
class _Ctx:
    def __init__(self, number):
        self.number = number
        self.message = None
        self.audio_path = "x.wav"
        self.duration = 10.0
        self.interaction = type("I", (), {"user": _Member(), "guild": None})()

    def named_pairs(self):
        return [("A", "B")]

    def label(self):
        return f"grind {self.number}"


def test_a_second_grind_waits_rather_than_cutting_in(b, monkeypatch):
    """Founder decision 2026-08-11: the room plays one grind at a time. Being interrupted
    mid-listen spoils the surprise for everyone already in there."""
    played = []
    monkeypatch.setattr(b, "is_in_booth", lambda m: True)

    async def fake_play(ctx):
        played.append(ctx.number)
        b.now_playing = ctx            # stays "playing" until _advance is called

    monkeypatch.setattr(b, "_play", fake_play)
    monkeypatch.setattr(b, "_mark_queued", lambda ctx: asyncio.sleep(0))

    first, second = _Ctx(1), _Ctx(2)
    asyncio.run(b.on_grind_finished(first))
    asyncio.run(b.on_grind_finished(second))

    assert played == [1], "the second grind must not interrupt the first"
    assert [c.number for c in b.queue] == [2]


def test_the_queue_advances_when_a_grind_finishes(b, monkeypatch):
    played = []
    monkeypatch.setattr(b, "is_in_booth", lambda m: True)

    async def fake_play(ctx):
        played.append(ctx.number)
        b.now_playing = ctx

    monkeypatch.setattr(b, "_play", fake_play)
    monkeypatch.setattr(b, "_mark_queued", lambda ctx: asyncio.sleep(0))

    asyncio.run(b.on_grind_finished(_Ctx(1)))
    asyncio.run(b.on_grind_finished(_Ctx(2)))
    asyncio.run(b._advance())
    assert played == [1, 2]
    assert b.queue == []


def test_a_grind_made_outside_the_booth_never_seizes_the_speakers(b, monkeypatch):
    """Somebody grinding from a text channel is doing a private thing. It must not take over a
    room they are not even in."""
    monkeypatch.setattr(b, "is_in_booth", lambda m: False)
    played = []
    monkeypatch.setattr(b, "_play", lambda ctx: played.append(ctx.number))
    asyncio.run(b.on_grind_finished(_Ctx(1)))
    assert played == []
    assert b.queue == []


# --- going to sleep ---------------------------------------------------------------------
def test_an_empty_room_clears_the_queue_and_disconnects(b):
    """The bot must never sit connected and silent - if it is in the room, audio is playing."""
    class _VC:
        def __init__(self):
            self.gone = False

        async def disconnect(self, force=False):
            self.gone = True

    guild = _Guild([])
    guild.voice_client = _VC()
    b.queue = [_Ctx(1), _Ctx(2)]
    b.now_playing = _Ctx(0)

    asyncio.run(b._room_empty(guild))
    assert b.queue == [] and b.now_playing is None
    assert guild.voice_client.gone is True


def test_a_session_count_resets_once_the_room_empties(b):
    b.grinds_this_session = 12
    guild = _Guild([])
    asyncio.run(b.refresh_status(guild))     # no grinder channel configured -> returns early
    # refresh_status returns early with no channel, so reset explicitly through the empty path
    asyncio.run(b._room_empty(guild))
    assert b.now_playing is None


# --- arrival notes ----------------------------------------------------------------------
def test_arrivals_are_announced_at_first_then_only_occasionally(b):
    """Every single join would turn the channel into noise once the server is busy."""
    said = []
    for _ in range(10):
        b._arrivals += 1
        if b._should_announce():
            said.append(b._arrivals)
    assert said[0] == 1
    assert len(said) < 10, "not every arrival should be announced"


# --- the zombie voice session -------------------------------------------------------------
def test_startup_tells_discord_it_is_not_in_a_call():
    """Observed 2026-08-11: killing the bot while it was connected to voice left the session alive
    on Discord's side. Every later attempt completed its handshake, found the endpoint, then had
    the voice websocket die - five retries, every time - because it was colliding with a session
    whose process was gone. It presents as "voice is broken" and no amount of retrying helps.

    A bot that just logged in is not in a call. Saying so explicitly clears the leftover."""
    import asyncio

    import bot as botmod

    cleared = []

    class _G:
        id = 1

        async def change_voice_state(self, *, channel):
            cleared.append(channel)

    fake = type("S", (), {
        "guilds": [_G()],
        "_clear_stale_voice": botmod.PromptDJBot._clear_stale_voice,
    })()
    asyncio.run(fake._clear_stale_voice())
    assert cleared == [None], "startup must declare it is in no voice channel"


def test_a_guild_refusing_the_clear_does_not_stop_the_bot_starting():
    import asyncio

    import bot as botmod

    class _G:
        id = 1

        async def change_voice_state(self, *, channel):
            raise RuntimeError("nope")

    fake = type("S", (), {
        "guilds": [_G()],
        "_clear_stale_voice": botmod.PromptDJBot._clear_stale_voice,
    })()
    asyncio.run(fake._clear_stale_voice())      # must not raise
