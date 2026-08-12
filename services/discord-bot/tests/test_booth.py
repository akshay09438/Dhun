"""The listening rooms: who plays where, who counts as an audience, and when to leave.

ROOMS, PLURAL. The founder keeps a category of voice channels and keeps adding to it, so "a room"
is any voice channel under that category rather than one fixed id. That is not a preference:
deleting the single configured channel on 2026-08-11 made playback silently stop working with
nothing in the log, because an id cannot survive delete-and-recreate and a category can.

WHAT THESE TESTS DO NOT COVER, stated plainly: real voice playback. A fake voice client is always
more forgiving than Discord - that is how seven bugs shipped past a green suite on 2026-08-11.
These cover the DECISIONS (which room, queue order, occupancy, sleep). Whether audio actually
comes out of the speakers needs a real room.
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import booth as boothmod  # noqa: E402

ROOMS_CAT = 777
OTHER_CAT = 888


class _Member:
    def __init__(self, name="someone", bot=False, in_channel=None):
        self.display_name = name
        self.bot = bot
        self.voice = type("V", (), {"channel": in_channel})() if in_channel else None


class _Room:
    """A voice channel: joinable, has members, knows its category."""

    def __init__(self, name="Bollywood_House", members=(), category_id=ROOMS_CAT, cid=1):
        self.id = cid
        self.name = name
        self.members = list(members)
        self.category = type("C", (), {"id": category_id})()

    async def connect(self):
        return None


class _TextChannel:
    """Has members and a category, cannot be joined. What a mis-set id looks like."""

    def __init__(self, category_id=ROOMS_CAT):
        self.id = 99
        self.name = "get-shit-done"
        self.members = [_Member("a")]
        self.category = type("C", (), {"id": category_id})()


class _Guild:
    def __init__(self, rooms=()):
        self.name = "Grinder"
        self.voice_channels = list(rooms)
        self.text_channels = []
        self.voice_client = None

    def get_channel(self, cid):
        for c in self.voice_channels + self.text_channels:
            if c.id == cid:
                return c
        return None


@pytest.fixture
def b(monkeypatch):
    monkeypatch.setattr(boothmod.CFG, "rooms_category_id", ROOMS_CAT, raising=False)
    monkeypatch.setattr(boothmod.CFG, "grinder_channel_id", None, raising=False)
    monkeypatch.setattr(boothmod.CFG, "fresh_grinds_channel_id", None, raising=False)
    return boothmod.Booth()


# --- which channels count as rooms -------------------------------------------------------
def test_any_voice_channel_in_the_category_is_a_room(b):
    """The founder adds rooms as the community grows. A new one must work with no config change -
    that is the entire reason this is a category and not a channel id."""
    assert b.is_a_room(_Room("Bollywood_House", cid=1)) is True
    assert b.is_a_room(_Room("Hollywood_Blends", cid=2)) is True
    assert b.is_a_room(_Room("a room added tomorrow", cid=3)) is True


def test_a_voice_channel_somewhere_else_is_not_a_room(b):
    """Grinds must not start playing in a general-chat voice channel that has nothing to do with
    listening together."""
    assert b.is_a_room(_Room("random hangout", category_id=OTHER_CAT)) is False


def test_a_text_channel_is_never_treated_as_a_room(b):
    """A text channel has members and a category too. Only being joinable makes it a room, and
    catching that here beats failing deep inside playback where it reads as 'voice is broken'."""
    assert b.is_a_room(_TextChannel()) is False


def test_with_no_rooms_category_configured_nothing_is_a_room(b, monkeypatch):
    """A missing setting disables the feature. It must never make the bot guess at a channel."""
    monkeypatch.setattr(boothmod.CFG, "rooms_category_id", None, raising=False)
    assert b.is_a_room(_Room()) is False
    assert b.room_of(_Member(in_channel=_Room())) is None


# --- who counts as an audience -----------------------------------------------------------
def test_the_bot_itself_is_not_an_audience(b):
    """Grinder sitting in a room must not make it look occupied, or it would keep playing to an
    empty room and never go to sleep."""
    assert b.listeners(_Room(members=[_Member("Grinder", bot=True)])) == 0


def test_people_in_a_room_are_counted(b):
    room = _Room(members=[_Member("a"), _Member("b"), _Member("Grinder", bot=True)])
    assert b.listeners(room) == 2


def test_occupancy_is_summed_across_every_room(b):
    guild = _Guild([_Room("one", [_Member("a")], cid=1),
                    _Room("two", [_Member("b"), _Member("c")], cid=2)])
    assert b.total_listeners(guild) == 3
    assert b.busiest_room(guild).name == "two"


# --- one grind at a time ------------------------------------------------------------------
class _Ctx:
    def __init__(self, number, room=None):
        self.number = number
        self.message = None
        self.audio_path = f"{number}.wav"
        self.duration = 10.0
        user = _Member(in_channel=room)
        self.interaction = type("I", (), {"user": user, "guild": None})()

    def named_pairs(self):
        return [("A", "B")]

    def label(self):
        return f"grind {self.number}"


def _records_what_played(monkeypatch):
    """Let the REAL playback path run - claiming a voice and all - and record what reached the
    audio player. Faking `_play` used to be enough; it is not any more, because whether a second
    room can be served now depends on whether an identity was actually claimed for the first."""
    played = []

    async def fake_play_in(channel, path, on_finished=None, start_at=0.0):
        played.append(int(str(path).split(".")[0]))

    monkeypatch.setattr(boothmod.voice_player, "play_in", fake_play_in)
    return played


def test_a_second_grind_waits_rather_than_cutting_in(b, monkeypatch):
    """One room, one mix at a time (founder decision 2026-08-11). Being interrupted mid-listen
    spoils the surprise for everyone already in the room."""
    played = _records_what_played(monkeypatch)
    monkeypatch.setattr(b, "_mark_queued", lambda ctx, **kw: asyncio.sleep(0))

    room = _Room()
    asyncio.run(b.on_grind_finished(_Ctx(1, room)))
    asyncio.run(b.on_grind_finished(_Ctx(2, room)))
    assert played == [1], "the second grind must not interrupt the first"
    assert [c.number for c in b.queue] == [2]


def test_with_one_identity_a_grind_from_another_room_still_waits(b, monkeypatch):
    """THE REGRESSION THAT MATTERS MOST. A bot application holds ONE voice connection per SERVER,
    so with nothing extra configured two busy rooms still cannot both be served - and the app must
    behave exactly as it did before any of the multi-room work existed."""
    played = _records_what_played(monkeypatch)
    monkeypatch.setattr(b, "_mark_queued", lambda ctx, **kw: asyncio.sleep(0))

    asyncio.run(b.on_grind_finished(_Ctx(1, _Room("one", cid=1))))
    asyncio.run(b.on_grind_finished(_Ctx(2, _Room("two", cid=2))))
    assert played == [1]
    assert len(b.queue) == 1


def test_the_queue_advances_when_a_grind_finishes(b, monkeypatch):
    played = _records_what_played(monkeypatch)
    monkeypatch.setattr(b, "_mark_queued", lambda ctx, **kw: asyncio.sleep(0))

    room = _Room()
    asyncio.run(b.on_grind_finished(_Ctx(1, room)))
    asyncio.run(b.on_grind_finished(_Ctx(2, room)))
    asyncio.run(b.deck(room).advance())
    assert played == [1, 2]
    assert b.queue == []


def test_a_grind_made_outside_every_room_never_seizes_the_speakers(b, monkeypatch):
    """Somebody grinding from a text channel is doing a private thing. It must not take over a
    room they are not even in."""
    played = _records_what_played(monkeypatch)
    asyncio.run(b.on_grind_finished(_Ctx(1, room=None)))
    assert played == [] and b.queue == []


def test_a_queued_grind_whose_owner_wandered_off_is_skipped(b, monkeypatch):
    """The room is re-checked at play time, not remembered. Playing into a room its owner has left
    is worse than not playing, and it would strand everything queued behind it."""
    monkeypatch.setattr(boothmod.voice_player, "play_in",
                        lambda *a, **k: pytest.fail("must not connect"))
    d = b.deck(_Room())
    asyncio.run(d.play_grind(_Ctx(1, room=None), None))
    assert d.now_playing is None


# --- going to sleep -----------------------------------------------------------------------
def test_all_rooms_empty_clears_the_queue_and_disconnects(b):
    """The bot must never sit connected and silent - if it is in a room, audio is playing."""
    class _VC:
        def __init__(self):
            self.gone = False

        async def disconnect(self, force=False):
            self.gone = True

    room = _Room()
    guild = _Guild([room])
    guild.voice_client = _VC()
    b.queue = [_Ctx(1), _Ctx(2)]
    d = b.deck(room)
    d.now_playing = _Ctx(0)

    asyncio.run(b._room_empty(guild))
    assert b.queue == [] and d.now_playing is None
    assert guild.voice_client.gone is True


# --- arrival notes ------------------------------------------------------------------------
def test_arrivals_are_announced_at_first_then_only_occasionally(b):
    """Every single join would turn the channel into noise once the server is busy."""
    said = []
    for _ in range(10):
        b._arrivals += 1
        if b._should_announce():
            said.append(b._arrivals)
    assert said[0] == 1
    assert len(said) < 10


# --- the config check ---------------------------------------------------------------------
def test_a_rooms_category_with_no_voice_channels_is_reported_loudly(b, monkeypatch):
    """The failure this prevents: the configured voice channel was deleted, the id matched nothing,
    and the bot answered "nobody is in a room" for everyone - silently, forever."""
    monkeypatch.setattr(boothmod.CFG, "rooms_category_id", 12345, raising=False)
    guild = _Guild([_Room("somewhere else", category_id=OTHER_CAT)])
    problems = b.check_config(guild)
    assert any("12345" in p and "no voice channels" in p for p in problems)
    assert any("somewhere else" in p for p in problems), \
        "it should name the channels that DO exist, so the fix is obvious"


def test_an_unset_rooms_category_is_reported(b, monkeypatch):
    monkeypatch.setattr(boothmod.CFG, "rooms_category_id", None, raising=False)
    assert any("ROOMS_CATEGORY" in p for p in b.check_config(_Guild()))


def test_the_check_never_guesses_a_replacement(b, monkeypatch):
    """Even with exactly one obvious candidate. A bot that quietly picks a different room to play
    music in is worse than one that says it cannot find the room."""
    monkeypatch.setattr(boothmod.CFG, "rooms_category_id", 12345, raising=False)
    guild = _Guild([_Room("the only one", category_id=OTHER_CAT)])
    b.check_config(guild)
    assert boothmod.CFG.rooms_category_id == 12345, "config must not be rewritten behind our back"
    assert b.rooms(guild) == [], "and it must still refuse to play anywhere"


# --- the zombie voice session --------------------------------------------------------------
def test_startup_tells_discord_it_is_not_in_a_call():
    """Killing the bot while connected left the session alive on Discord's side. Every later
    attempt completed its handshake, found the endpoint, then had the websocket die - five retries,
    every time - colliding with a session whose process was gone. It presents as "voice is broken"
    and no amount of retrying helps."""
    import bot as botmod

    cleared = []

    class _G:
        id = 1

        async def change_voice_state(self, *, channel):
            cleared.append(channel)

    fake = type("S", (), {"guilds": [_G()],
                          "_clear_stale_voice": botmod.PromptDJBot._clear_stale_voice})()
    asyncio.run(fake._clear_stale_voice())
    assert cleared == [None]


def test_a_guild_refusing_the_clear_does_not_stop_the_bot_starting():
    import bot as botmod

    class _G:
        id = 1

        async def change_voice_state(self, *, channel):
            raise RuntimeError("nope")

    fake = type("S", (), {"guilds": [_G()],
                          "_clear_stale_voice": botmod.PromptDJBot._clear_stale_voice})()
    asyncio.run(fake._clear_stale_voice())      # must not raise


# --- the card must never claim something is playing when it is not -------------------------
def test_the_live_banner_only_goes_up_after_the_connection_succeeds(b, monkeypatch):
    """Observed 2026-08-11: a card read "PLAYING LIVE IN BOLLYWOOD_HOUSE - 2 listening" while the
    voice handshake was failing five times over and nothing was audible. The banner was posted
    before the connection was even attempted."""
    edits = []

    class _Ctx2(_Ctx):
        def __init__(self, number, room):
            super().__init__(number, room)
            self.message = type("M", (), {
                "edit": lambda _self, **kw: edits.append(kw) or _noop()})()

    def _noop():
        async def f():
            return None
        return f()

    async def boom(*a, **k):
        raise RuntimeError("voice websocket closed with 4017")

    monkeypatch.setattr(boothmod.voice_player, "play_in", boom)
    room = _Room()
    asyncio.run(b.deck(room).play_grind(_Ctx2(1, room), room))

    blob = " ".join((e["embed"].description or "") for e in edits if "embed" in e)
    assert "PLAYING LIVE" not in blob, "a failed connection must never claim to be playing"
    assert "couldn't play it out loud" in blob, "it should say the out-loud part failed"


def test_a_failed_playout_does_not_count_as_a_session_grind(b, monkeypatch):
    """The status message counts what the room actually heard."""
    async def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(boothmod.voice_player, "play_in", boom)
    monkeypatch.setattr(b, "_say_it_did_not_play", lambda ctx: asyncio.sleep(0))
    room = _Room()
    asyncio.run(b.deck(room).play_grind(_Ctx(1, room), room))
    assert b.grinds_this_session == 0
