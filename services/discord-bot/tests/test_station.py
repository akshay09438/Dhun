"""The station, the controls, and the listening record.

WHY THIS EXISTS. Until 2026-08-12 a listening room played one grind and then went silent with the
bot still sitting in it. That is the difference between "a room can play a mix" - which was proven
by ear that morning - and "a Discord community with continuous music", which is the recorded next
phase. A room that is quiet most of the time also makes the two blocking data gaps unmeasurable:
nobody can drop off from silence.

WHAT THESE TESTS CAN AND CANNOT PROVE. booth.py's own honesty note applies: a fake voice client is
always more forgiving than Discord, and that is exactly how bugs shipped past a green suite on
2026-08-11. So these cover the DECISIONS - what airs next, what outranks what, who may skip, what
gets recorded - and never claim the audio came out. The audio needs a real room and a real ear.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import booth as booth_mod
import store


# --- doubles -----------------------------------------------------------------------------------

class FakeVoiceClient:
    def __init__(self):
        self.playing = True
        self.stops = 0

    def is_playing(self):
        return self.playing

    def stop(self):
        self.stops += 1
        self.playing = False


class FakeChannel:
    def __init__(self, cid, name, guild, members=()):
        self.id = cid
        self.name = name
        self.guild = guild
        self.members = list(members)
        self.category = type("Cat", (), {"id": 999})()

    def connect(self):  # marks this as a voice channel for is_a_room
        raise AssertionError("tests must never really connect")


class FakeGuild:
    def __init__(self):
        self.id = 1
        self.voice_channels = []
        self.voice_client = None

    def get_channel(self, _id):
        return None


class FakeMember:
    def __init__(self, uid, guild, channel=None, bot=False):
        self.id = uid
        self.display_name = f"user{uid}"
        self.guild = guild
        self.bot = bot
        self.voice = type("VS", (), {"channel": channel})()


@pytest.fixture(autouse=True)
def _fresh_store(tmp_path):
    """A clean database per test. The store keeps one module-level connection, so without this a
    grind made in one test would still be on air in the next."""
    store.reset_for_tests(tmp_path / "grinder.db")
    yield


@pytest.fixture
def booth(tmp_path, monkeypatch):
    monkeypatch.setattr(booth_mod.CFG, "rooms_category_id", 999, raising=False)
    b = booth_mod.Booth()
    return b


def _grind_on_disk(tmp_path, number_hint: str, fires: int = 0) -> int:
    """A finished grind whose audio really exists, so the station's exists() check passes."""
    audio = tmp_path / f"{number_hint}.wav"
    audio.write_bytes(b"RIFF fake")
    n = store.new_grind(user_id=7, user_name="a", pairs=[["b", "v", "Beat", "Voc"]],
                        created_at="2026-08-12T00:00:00+00:00")
    store.set_audio_path(n, str(audio))
    for i in range(fires):
        store.add_reaction(grind_number=n, user_id=100 + i, emoji=store.FIRE,
                           when="2026-08-12T00:00:00+00:00")
    return n


# --- what the station chooses -------------------------------------------------------------------

def test_the_most_loved_mix_airs_first(booth, tmp_path):
    """Ordered by the community's OWN votes. Grinder never forms an opinion of its own."""
    _grind_on_disk(tmp_path, "quiet", fires=0)
    loved = _grind_on_disk(tmp_path, "loved", fires=3)
    _grind_on_disk(tmp_path, "ok", fires=1)
    assert [r["number"] for r in store.station_candidates()][0] == loved


def test_a_mix_nobody_reacted_to_is_still_eligible(booth, tmp_path):
    """A brand-new room has no reactions at all. If unreacted mixes were excluded it would have
    nothing to play and would fall silent - the exact bug being fixed."""
    n = _grind_on_disk(tmp_path, "lonely", fires=0)
    assert n in [r["number"] for r in store.station_candidates()]


def test_a_grind_with_no_audio_yet_is_never_offered(booth, tmp_path):
    store.new_grind(user_id=7, user_name="a", pairs=[], created_at="2026-08-12T00:00:00+00:00")
    assert store.station_candidates() == []


def test_a_swept_file_is_skipped_not_crashed_on(booth, tmp_path, monkeypatch):
    """THE JANITOR INTERACTION. The disk cleaner deletes old renders; the database still lists
    them. The station must step over a missing file and air the next one, never error."""
    gone = _grind_on_disk(tmp_path, "gone", fires=9)      # most loved, but...
    Path(tmp_path / "gone.wav").unlink()                  # ...the janitor took it
    alive = _grind_on_disk(tmp_path, "alive", fires=1)

    guild = FakeGuild()
    room = FakeChannel(10, "Bollywood_House", guild, members=[FakeMember(2, guild)])
    guild.voice_channels = [room]

    aired = []
    async def fake_play_in(ch, path, on_finished=None):
        aired.append(Path(path).stem)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    asyncio.run(booth._play_station(guild))
    assert aired == ["alive"], "the station must skip a swept file, not fall over on it"
    assert booth.station_number == alive


def test_the_station_stays_quiet_when_nobody_is_listening(booth, tmp_path, monkeypatch):
    """Playing to an empty room burns a voice connection for an audience of nobody."""
    _grind_on_disk(tmp_path, "x", fires=1)
    guild = FakeGuild()
    guild.voice_channels = [FakeChannel(10, "empty", guild, members=[])]
    called = []
    monkeypatch.setattr(booth_mod.voice_player, "play_in",
                        lambda *a, **k: called.append(1))
    asyncio.run(booth._play_station(guild))
    assert called == []


def test_the_same_mix_does_not_air_twice_in_a_row(booth, tmp_path, monkeypatch):
    a = _grind_on_disk(tmp_path, "a", fires=2)
    b = _grind_on_disk(tmp_path, "b", fires=1)
    guild = FakeGuild()
    guild.voice_channels = [FakeChannel(10, "r", guild, members=[FakeMember(2, guild)])]

    async def fake_play_in(ch, path, on_finished=None):
        pass
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    asyncio.run(booth._play_station(guild))
    first = booth.station_number
    asyncio.run(booth._play_station(guild))
    assert booth.station_number != first
    assert {first, booth.station_number} == {a, b}


# --- stop means stop ------------------------------------------------------------------------------

def test_stop_parks_the_station_so_it_does_not_restart_itself(booth, tmp_path, monkeypatch):
    """Without this the finish callback immediately airs the next thing and /stop does nothing
    visible - the most obvious possible bug in a stop button."""
    _grind_on_disk(tmp_path, "a", fires=1)
    guild = FakeGuild()
    room = FakeChannel(10, "r", guild)
    member = FakeMember(2, guild, channel=room)
    room.members = [member]
    guild.voice_channels = [room]
    guild.voice_client = FakeVoiceClient()

    played = []
    async def fake_play_in(ch, path, on_finished=None):
        played.append(path)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    msg = asyncio.run(booth.stop_playback(member))
    assert "quiet" in msg.lower()
    asyncio.run(booth._play_station(guild))
    assert played == [], "/stop must not be undone by the station starting itself again"


def test_skip_requires_being_in_the_room(booth):
    guild = FakeGuild()
    outsider = FakeMember(3, guild, channel=None)
    assert "join a listening room" in asyncio.run(booth.skip(outsider)).lower()


def test_anyone_in_the_room_may_skip_not_just_the_owner(booth):
    """The founder's call on 2026-08-12. A bad mix whose owner has left must not hold the room."""
    guild = FakeGuild()
    room = FakeChannel(10, "r", guild)
    someone_else = FakeMember(42, guild, channel=room)   # did NOT make what is playing
    room.members = [someone_else]
    guild.voice_channels = [room]
    guild.voice_client = FakeVoiceClient()
    assert asyncio.run(booth.skip(someone_else)) == "Skipped."
    assert guild.voice_client.stops == 1


def test_skipping_silence_says_so_rather_than_pretending(booth):
    guild = FakeGuild()
    room = FakeChannel(10, "r", guild)
    m = FakeMember(2, guild, channel=room)
    room.members = [m]
    guild.voice_channels = [room]
    guild.voice_client = FakeVoiceClient()
    guild.voice_client.playing = False
    assert "nothing is playing" in asyncio.run(booth.skip(m)).lower()


# --- the listening record --------------------------------------------------------------------------

def test_an_arrival_and_a_departure_record_how_long_they_stayed():
    store.room_arrival(guild_id=1, room_id=10, room_name="r", user_id=5, user_name="e",
                       when="2026-08-12T10:00:00+00:00")
    store.room_departure(room_id=10, user_id=5, when="2026-08-12T10:05:00+00:00", seconds=300.0)
    s = store.listening_summary()
    assert s["sessions"] == 1 and s["people"] == 1
    assert s["avg_secs"] == pytest.approx(300.0)
    assert s["in_a_room_now"] == 0


def test_a_second_arrival_for_someone_already_in_the_room_is_ignored():
    """Discord fires voice-state updates for mute, deafen and camera as well as joins. Counting
    those as arrivals would invent listeners who never walked in and make every number a lie."""
    for _ in range(3):
        store.room_arrival(guild_id=1, room_id=10, room_name="r", user_id=6, user_name="f",
                           when="2026-08-12T10:00:00+00:00")
    assert store.listening_summary()["in_a_room_now"] == 1


def test_a_departure_with_no_arrival_is_ignored_rather_than_invented():
    """The bot restarting mid-session leaves people in a room it has no record of admitting."""
    store.room_departure(room_id=10, user_id=999, when="2026-08-12T10:05:00+00:00", seconds=1.0)
    assert store.listening_summary()["sessions"] == 0


