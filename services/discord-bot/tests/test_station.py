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
import json
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


# --- stop means stop ------------------------------------------------------------------------------


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




# --- skipping INSIDE a set, and picking up where you stopped -------------------------------------
# A set is ONE continuous audio file. Before 2026-08-12 a skip could only abandon all five members,
# because nothing knew where one track ended and the next began. The engine already records that
# (`seam_at` per member); these prove the booth uses it.

def _room_with(booth, member_id=2):
    guild = FakeGuild()
    room = FakeChannel(10, "Bollywood_House", guild)
    member = FakeMember(member_id, guild, channel=room)
    room.members = [member]
    guild.voice_channels = [room]
    guild.voice_client = FakeVoiceClient()
    return guild, room, member


# Position, seams and the playback token belong to ONE ROOM - they moved onto its deck when a
# second room became able to have sound at the same time. The assertions below are unchanged; only
# the thing being poked at is now named per-room, which is the whole point of the change.
def _deck(booth, room):
    return booth.deck(room)


def test_skip_moves_to_the_next_track_inside_a_set(booth, tmp_path, monkeypatch):
    """THE FOUNDER'S CASE: five tracks, half way through, skip should land on the next one - not
    throw the whole set away."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "set.wav"; audio.write_bytes(b"RIFF")
    seeks = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        seeks.append(start_at)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    d._mark_playing(str(audio), offset=0.0, seams=[160.0, 336.0, 512.0, 701.0])
    d._now_started = d._now_started - 200          # pretend 200s have played

    msg = asyncio.run(booth.skip(member))
    assert seeks == [336.0], "should seek to the NEXT seam after 200s, not restart or abandon"
    assert "track 3" in msg
    assert guild.voice_client.stops == 0, "seeking must not stop playback - that would end the set"


def test_skip_past_the_last_track_moves_on_properly(booth, tmp_path, monkeypatch):
    """At the end of the set there is no next seam, so skip must fall back to ending the track and
    letting the queue or the station take over."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "set.wav"; audio.write_bytes(b"RIFF")
    monkeypatch.setattr(booth_mod.voice_player, "play_in",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not seek")))
    d._mark_playing(str(audio), offset=0.0, seams=[160.0])
    d._now_started = d._now_started - 300          # past the only seam

    assert asyncio.run(booth.skip(member)) == "Skipped."
    assert guild.voice_client.stops == 1


def test_a_single_mix_has_no_seams_so_skip_just_moves_on(booth, tmp_path, monkeypatch):
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "mix.wav"; audio.write_bytes(b"RIFF")
    d._mark_playing(str(audio), seams=[])
    assert asyncio.run(booth.skip(member)) == "Skipped."
    assert guild.voice_client.stops == 1


def test_double_skip_does_not_land_back_on_the_seam_just_crossed(booth, tmp_path, monkeypatch):
    """Without a guard, seeking to 160.0 and immediately skipping again finds 160.0 still 'ahead'
    and sticks there forever."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "set.wav"; audio.write_bytes(b"RIFF")
    seeks = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        seeks.append(start_at)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    d._mark_playing(str(audio), offset=0.0, seams=[160.0, 336.0])
    d._now_started = d._now_started - 100
    asyncio.run(booth.skip(member))        # -> 160.0
    asyncio.run(booth.skip(member))        # must go on to 336.0, not stick at 160.0
    assert seeks == [160.0, 336.0]


def test_stop_remembers_the_position_and_play_resumes_there(booth, tmp_path, monkeypatch):
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "set.wav"; audio.write_bytes(b"RIFF")
    resumed = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        resumed.append(start_at)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    d._mark_playing(str(audio), offset=0.0, seams=[])
    d._now_started = d._now_started - 90           # 90s in

    asyncio.run(booth.stop_playback(member))
    guild.voice_client.playing = False                     # the room really is quiet now
    asyncio.run(booth.play(member))

    assert resumed and 89 <= resumed[0] <= 92, f"should resume near 90s, got {resumed}"


def test_stop_no_longer_bins_everybody_elses_queued_grinds(booth, tmp_path):
    """It used to clear the queue, so one person could discard everyone else's waiting mixes with
    nobody being told why - a much bigger hammer than 'anyone in the room can stop' implies."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    booth.queue.extend(["someone-elses-grind", "and-another"])
    asyncio.run(booth.stop_playback(member))
    assert len(booth.queue) == 2


def test_play_needs_you_to_be_in_a_room(booth):
    guild = FakeGuild()
    assert "join a listening room" in asyncio.run(booth.play(FakeMember(9, guild))).lower()


# --- the "it just pauses" bug (founder-reported 2026-08-12) ----------------------------------------
# Seams only began being WRITTEN on 2026-08-12, so every set made before that had none stored, and
# /skip on one silently degraded to "stop". The engine has always known them.


def test_a_looked_up_seam_is_written_back_so_it_is_asked_once(booth, tmp_path, monkeypatch):
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "s.wav"; audio.write_bytes(b"RIFF")
    calls = []

    async def fake_lookup(ref_id):
        calls.append(ref_id)
        return [90.0]
    booth.seam_lookup = fake_lookup
    monkeypatch.setattr(booth_mod.voice_player, "play_in",
                        lambda *a, **k: asyncio.sleep(0))

    n = store.new_grind(user_id=7, user_name="a", pairs=[], created_at="x")
    store.set_audio_path(n, str(audio))
    seams = asyncio.run(booth._resolve_seams(n, "set-xyz", None))
    assert seams == [90.0]
    assert json.loads(store.get(n)["seams"]) == [90.0], "the answer must be cached in the store"


# --- the stomped seek (founder-reported 2026-08-12: "said track 2, track 2 didn't play") ---------
# discord.py's vc.stop() FIRES the current source's `after` callback, and voice_player.play_in
# calls stop() before starting anything. So deliberately replacing the audio delivers a "track
# finished" that is not true - and acting on it started something else OVER the top.

def test_a_seek_is_not_undone_by_the_callback_from_the_track_it_replaced(booth, tmp_path,
                                                                        monkeypatch):
    """THE REPORTED BUG. /skip said "Skipped to track 2" and track 2 did not play, because the
    stopped track's finish-callback ran a moment later and started something else."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "set.wav"; audio.write_bytes(b"RIFF")

    started = []
    captured = {}

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        started.append((Path(path).stem, start_at))
        captured["cb"] = on_finished                    # the CURRENT track's callback
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    d._mark_playing(str(audio), offset=0.0, seams=[160.0], guild=guild)
    d._now_started = d._now_started - 100
    # The callback the OLD track holds. The token must be captured NOW, by value - reading it
    # later would read the token of whatever replaced it, which is the whole thing being guarded.
    old_token = d._play_token
    stale_cb = lambda: d.advance(old_token)

    asyncio.run(booth.skip(member))
    assert started[-1] == ("set", 160.0), "the seek itself must happen"

    # now the stopped track's callback arrives, late, as it does in real life
    asyncio.run(stale_cb())

    assert started[-1] == ("set", 160.0), (
        "the seek was stomped: something started over the top of the track /skip just began"
    )


def test_a_genuine_track_ending_still_advances(booth, tmp_path, monkeypatch):
    """The guard must not make the room deaf to real endings - that would trade one bug for
    another. A real ending takes the next thing SOMEBODY ASKED FOR, and with nothing waiting the
    room goes quiet and lets its identity go."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    audio = tmp_path / "cur.wav"; audio.write_bytes(b"RIFF")

    played = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        played.append(Path(path).stem)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    booth.queue.append(_QueuedFor(room, tmp_path / "next.wav"))
    d._mark_playing(str(audio), guild=guild)
    tok = d._begin_playback()          # the token the CURRENT playback holds
    asyncio.run(d.advance(tok))        # it really finished
    assert played == ["next"], "a real ending must take the next requested grind"


# --- NOTHING STARTS BY ITSELF (founder decision, 2026-08-12) -------------------------------------
# A room used to replay past mixes when its queue emptied, and walking into a quiet room started
# one. Built to stop rooms feeling dead; used for real by the founder, it meant music appearing that
# nobody had asked for. Removed. These pin the new promise: sound exists in a room because a person
# asked for it, and for no other reason.

class _QueuedFor:
    """A finished grind waiting its turn, owned by somebody sitting in `room`."""

    def __init__(self, room, path):
        self.number = 99
        self.message = None
        self.audio_path = str(path)
        self.duration = 10.0
        user = FakeMember(77, room.guild, channel=room)
        self.interaction = type("I", (), {"user": user, "guild": room.guild})()

    def named_pairs(self):
        return [("A", "B")]

    def label(self):
        return "queued grind"


def test_a_finished_mix_with_nothing_waiting_starts_nothing(booth, tmp_path, monkeypatch):
    """THE FOUNDER'S REPORT. The room used to put a past mix on by itself here."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    _grind_on_disk(tmp_path, "an_old_favourite", fires=9)   # exactly what it used to reach for
    audio = tmp_path / "cur.wav"; audio.write_bytes(b"RIFF")

    played = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        played.append(Path(path).stem)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    d._mark_playing(str(audio), guild=guild)
    asyncio.run(d.advance())

    assert played == [], "nothing may start that nobody asked for"
    assert d.now_playing is None


def test_walking_into_a_quiet_room_starts_nothing(booth, tmp_path, monkeypatch):
    """It used to start music the moment somebody walked in."""
    guild, room, member = _room_with(booth)
    _grind_on_disk(tmp_path, "an_old_favourite", fires=9)

    played = []

    async def fake_play_in(ch, path, on_finished=None, start_at=0.0):
        played.append(Path(path).stem)
    monkeypatch.setattr(booth_mod.voice_player, "play_in", fake_play_in)

    before = type("B", (), {"channel": None})()
    after = type("A", (), {"channel": room})()
    asyncio.run(booth.on_voice_state_update(member, before, after))

    assert played == [], "arriving is not a request for music"


def test_arriving_back_still_cancels_the_empty_room_timer(booth, tmp_path):
    """The one thing arriving DOES do: someone who stepped out finds their music still playing."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    d.empty_since = 1.0

    before = type("B", (), {"channel": None})()
    after = type("A", (), {"channel": room})()
    asyncio.run(booth.on_voice_state_update(member, before, after))

    assert d.empty_since is None


def test_play_with_nothing_paused_says_so_rather_than_inventing_something(booth, tmp_path,
                                                                          monkeypatch):
    """/play now does exactly one job: pick up whatever /stop paused."""
    guild, room, member = _room_with(booth)
    _grind_on_disk(tmp_path, "an_old_favourite", fires=9)
    guild.voice_client.playing = False

    monkeypatch.setattr(booth_mod.voice_player, "play_in",
                        lambda *a, **k: pytest.fail("nothing was asked for"))

    msg = asyncio.run(booth.play(member))
    assert "grind" in msg.lower(), msg


def test_play_on_a_swept_file_says_so_instead_of_failing(booth, tmp_path, monkeypatch):
    """The disk janitor can sweep a mix while the room is paused. /play must not error at somebody -
    it should say plainly that there is nothing to pick up."""
    guild, room, member = _room_with(booth)
    d = _deck(booth, room)
    d._paused_at = (str(tmp_path / "gone.wav"), 42.0, [])    # never existed
    guild.voice_client.playing = False

    monkeypatch.setattr(booth_mod.voice_player, "play_in",
                        lambda *a, **k: pytest.fail("there is nothing to play"))

    msg = asyncio.run(booth.play(member))
    assert "grind" in msg.lower(), msg
    assert d._paused_at is None, "the gone file must be forgotten, not retried forever"
