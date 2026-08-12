"""Who gets a voice, and whose copy of the room they play into.

THE WALL: a Discord bot application holds ONE voice connection per SERVER. So "can two rooms have
sound at once" is entirely a question of how many IDENTITIES are logged in, and these tests cover
the handing-out of those identities.

THE SUBTLE ONE, and the reason `resolve` exists at all: a channel object belongs to the client that
fetched it. `voice_player.play_in` reaches for `channel.guild.voice_client`, so handing it a channel
belonging to the MAIN bot connects the MAIN bot - no matter which identity we believed we were
using. An extra voice must therefore look the room up through its OWN client first. Get that wrong
and two rooms quietly play through one connection, which sounds exactly like the bug we are fixing.

WHAT THESE CANNOT PROVE: that audio comes out. A fake client is always more forgiving than Discord.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import speakers  # noqa: E402
import voices  # noqa: E402

ROOM_A, ROOM_B, ROOM_C = 101, 102, 103


class _Channel:
    def __init__(self, cid, name="a room"):
        self.id = cid
        self.name = name


class _Client:
    """Stands in for a logged-in discord.Client: it can look up channels it can see."""

    def __init__(self, visible=()):
        self._visible = {c.id: c for c in visible}

    def get_channel(self, cid):
        return self._visible.get(cid)


def _box(extras=0, *, visible=None):
    pool = speakers.SpeakerPool([f"token-{i}" for i in range(extras)])
    for s in pool.speakers:
        s.client = _Client(visible if visible is not None else
                           [_Channel(ROOM_A), _Channel(ROOM_B), _Channel(ROOM_C)])
    return voices.VoiceBox(pool)


# --- how many voices exist ------------------------------------------------------------------
def test_with_no_extra_tokens_there_is_exactly_one_voice():
    """The default, and the most important case in this file: nothing configured must behave
    EXACTLY as the app did before any of this existed."""
    box = _box(0)
    assert box.rooms_with_sound == 1
    assert box.claim(ROOM_A) is box.main
    assert box.claim(ROOM_B) is None, "one identity cannot hold two rooms - that is the wall"


def test_each_extra_token_is_one_more_room_with_sound():
    assert _box(1).rooms_with_sound == 2
    assert _box(2).rooms_with_sound == 3


# --- who gets handed out, and in what order -------------------------------------------------
def test_the_main_bot_is_handed_out_first():
    """Main-first is what makes zero-speaker behaviour identical to today. If an extra were handed
    out first, the single-room case would start routing through an identity that may not exist."""
    box = _box(2)
    assert box.claim(ROOM_A).is_main is True


def test_a_second_room_gets_an_extra_voice():
    box = _box(1)
    first = box.claim(ROOM_A)
    second = box.claim(ROOM_B)
    assert first.is_main is True
    assert second is not None and second.is_main is False
    assert first is not second


def test_when_every_voice_is_busy_the_answer_is_none_not_a_stolen_one():
    """None is a NORMAL answer - the room waits. Handing back a voice that is already playing
    somewhere else would cut off a room mid-listen, which is the one thing a listening room must
    never do to the people sitting in it."""
    box = _box(1)
    box.claim(ROOM_A)
    box.claim(ROOM_B)
    assert box.claim(ROOM_C) is None


def test_claiming_the_same_room_twice_returns_the_same_voice():
    """Re-claiming must be a no-op. A room asking again mid-song must not burn a second identity."""
    box = _box(2)
    first = box.claim(ROOM_A)
    assert box.claim(ROOM_A) is first
    assert box.claim(ROOM_B) is not first


def test_one_voice_is_never_serving_two_rooms():
    box = _box(2)
    claimed = [box.claim(r) for r in (ROOM_A, ROOM_B, ROOM_C)]
    rooms = [v.room_id for v in claimed]
    assert sorted(rooms) == [ROOM_A, ROOM_B, ROOM_C]
    assert len({id(v) for v in claimed}) == 3


def test_a_room_is_never_handed_two_voices():
    box = _box(2)
    box.claim(ROOM_A)
    box.claim(ROOM_A)
    assert sum(1 for v in box.all_voices if v.room_id == ROOM_A) == 1


# --- giving it back --------------------------------------------------------------------------
def test_releasing_frees_the_voice_for_somebody_else():
    box = _box(0)
    box.claim(ROOM_A)
    assert box.claim(ROOM_B) is None
    box.release(ROOM_A)
    assert box.claim(ROOM_B) is box.main


def test_releasing_a_room_nobody_holds_is_fine():
    """A room can empty in several ways at once - the last person leaves, playback ends, the bot
    restarts - and none of them should have to check first."""
    box = _box(1)
    assert box.release(ROOM_A) is None
    box.claim(ROOM_A)
    assert box.release(ROOM_A) is not None
    assert box.release(ROOM_A) is None


def test_release_all_lets_go_of_everything():
    box = _box(2)
    box.claim(ROOM_A)
    box.claim(ROOM_B)
    box.release_all()
    assert all(v.free for v in box.all_voices)


def test_holder_of_names_who_has_the_room():
    box = _box(1)
    assert box.holder_of(ROOM_A) is None
    v = box.claim(ROOM_A)
    assert box.holder_of(ROOM_A) is v


# --- whose copy of the room ------------------------------------------------------------------
def test_the_main_voice_plays_into_the_room_it_was_given():
    box = _box(0)
    room = _Channel(ROOM_A)
    assert box.main.resolve(room) is room


def test_an_extra_voice_looks_the_room_up_through_its_own_client():
    """THE BUG THIS PREVENTS: `play_in` uses `channel.guild.voice_client`, which is per-CLIENT
    state. Reusing the main bot's channel object would connect the main bot every time and the
    second room would stay silent while everything looked correct in the log."""
    mine = _Channel(ROOM_B, "Hollywood_Blends")
    box = _box(1, visible=[mine])
    box.claim(ROOM_A)                       # main takes the first room
    extra = box.claim(ROOM_B)
    theirs = _Channel(ROOM_B, "Hollywood_Blends")   # the MAIN bot's copy of the same room
    resolved = extra.resolve(theirs)
    assert resolved is mine, "it must use its own client's copy, not the one it was handed"
    assert resolved is not theirs


def test_an_extra_voice_that_cannot_see_the_room_resolves_to_nothing():
    """The likeliest real-world misconfiguration by far: the second identity was invited to the
    server but not given View Channel / Connect on the rooms category. It must come back as None so
    the caller can fall back and SAY so, rather than failing somewhere deep in the audio path."""
    box = _box(1, visible=[])
    box.claim(ROOM_A)
    extra = box.claim(ROOM_B)
    assert extra.resolve(_Channel(ROOM_B)) is None


def test_an_extra_voice_with_no_client_at_all_resolves_to_nothing():
    """A speaker whose login failed. It must not take the working voices down with it."""
    pool = speakers.SpeakerPool(["token-0"])
    box = voices.VoiceBox(pool)             # client left as None, i.e. never logged in
    box.claim(ROOM_A)
    assert box.claim(ROOM_B).resolve(_Channel(ROOM_B)) is None


# --- what the log says -------------------------------------------------------------------------
def test_the_startup_line_says_how_many_rooms_can_have_sound():
    """So the founder learns the limit from the log at startup, rather than from a room that stays
    quiet all night."""
    assert "ONE room" in voices.describe(_box(0))
    assert "2 rooms" in voices.describe(_box(1))
    assert "3 rooms" in voices.describe(_box(2))


def test_a_voice_says_which_one_it_is_in_plain_words():
    box = _box(1)
    assert "main" in box.claim(ROOM_A).label.lower()
    assert "extra" in box.claim(ROOM_B).label.lower()


@pytest.mark.parametrize("extras", [0, 1, 2, 5])
def test_a_room_can_always_be_released_and_re_claimed(extras):
    """Rooms fill and empty all night. Nothing may leak - after a full cycle every voice is free."""
    box = _box(extras)
    for _ in range(3):
        for room in (ROOM_A, ROOM_B, ROOM_C):
            box.claim(room)
        for room in (ROOM_A, ROOM_B, ROOM_C):
            box.release(room)
        assert all(v.free for v in box.all_voices)
