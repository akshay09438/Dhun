"""More than one room with sound in it.

One Discord bot application holds ONE voice connection per SERVER - so with a single Grinder,
every listening room but one is permanently silent, and adding rooms adds silent rooms. The only
fix is extra bot identities, which are free.

⚠️ The audio path here is UNPROVEN. As of 2026-08-12 voice DOES work on this machine (on the Intel
environment - see the handoff), but no audio has ever flowed through this pool: it is not yet wired
into booth.py. What these pin is every DECISION the pool makes, because a pool that can only be
tested by connecting to Discord is a pool that never gets tested.
"""
import os

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import speakers  # noqa: E402


def _pool(n=2):
    return speakers.SpeakerPool([f"token-{i}" for i in range(n)])


# --- the default: nothing configured, nothing changes -----------------------------------

def test_with_no_extra_identities_the_pool_gives_nothing_and_says_so():
    """Zero configured is the ordinary setup. `claim` returning None is a normal answer - the
    caller falls back to the main bot, which is exactly today's behaviour."""
    pool = speakers.SpeakerPool([])
    assert len(pool) == 0
    assert pool.claim(room_id=1) is None
    assert pool.rooms_with_sound == 1, "the main bot can still hold one room"


def test_the_startup_line_tells_the_founder_the_real_limit():
    """Otherwise the limit is discovered by a room mysteriously staying quiet."""
    assert "ONE room" in speakers.describe(speakers.SpeakerPool([]))
    assert "3 rooms" in speakers.describe(_pool(2)), "2 extras + the main bot = 3"


# --- handing out rooms ------------------------------------------------------------------

def test_two_rooms_can_have_sound_at_the_same_time():
    """The whole point. Bollywood_House and Hollywood_Blends both live at once."""
    pool = _pool(2)
    a = pool.claim(room_id=111)
    b = pool.claim(room_id=222)
    assert a is not None and b is not None
    assert a is not b, "the same identity cannot hold two rooms - it is one connection"


def test_a_room_is_never_handed_to_two_speakers():
    """Two speakers in one room would play two different grinds over each other, which is worse
    than silence for the people sitting in it."""
    pool = _pool(3)
    first = pool.claim(room_id=111)
    again = pool.claim(room_id=111)
    assert again is first, "re-claiming a room we already hold must be a no-op"
    assert sum(1 for s in pool.speakers if not s.free) == 1


def test_when_every_speaker_is_busy_the_answer_is_no_not_a_stolen_room():
    """Handing back a speaker that is already playing elsewhere would cut off whatever those
    listeners were hearing. The caller waits instead."""
    pool = _pool(2)
    pool.claim(room_id=111)
    pool.claim(room_id=222)
    assert pool.claim(room_id=333) is None
    assert pool.holder_of(111) is not None and pool.holder_of(222) is not None


def test_a_released_room_frees_its_speaker_for_the_next_one():
    pool = _pool(1)
    pool.claim(room_id=111)
    assert pool.claim(room_id=222) is None
    pool.release(111)
    assert pool.claim(room_id=222) is not None


def test_releasing_a_room_nobody_holds_is_harmless():
    """A room empties in several ways at once - the last person leaves, playback ends, the bot
    restarts - and none of those should have to check first."""
    pool = _pool(1)
    assert pool.release(999) is None
    pool.release_all()          # must not raise on an idle pool


# --- the mistake that would silently break a room ---------------------------------------

def test_the_same_token_pasted_twice_is_not_treated_as_two_identities():
    """An easy copy-paste error with a nasty failure: the second copy is the SAME login, so
    Discord would move the one connection and silently kill the first room mid-grind."""
    pool = speakers.SpeakerPool(["same-token", "same-token", " same-token "])
    assert len(pool) == 1


def test_blank_entries_are_ignored():
    """A trailing comma in the .env must not create a speaker that can never log in."""
    assert len(speakers.SpeakerPool(["a", "", "  ", "b"])) == 2


def test_config_reads_the_extra_tokens_from_the_environment(monkeypatch):
    import botconfig
    monkeypatch.setenv("GRINDER_ROOM_TOKENS", "tok-a, tok-b ,")
    assert botconfig._token_list("GRINDER_ROOM_TOKENS") == ["tok-a", "tok-b"]
    monkeypatch.delenv("GRINDER_ROOM_TOKENS")
    assert botconfig._token_list("GRINDER_ROOM_TOKENS") == []


# --- the availability gate must not lie ---------------------------------------------------

def test_the_voice_gate_checks_BOTH_libraries_not_just_one(monkeypatch):
    """It used to check PyNaCl only. discord.py 2.7 requires `davey` unconditionally for ANY
    voice - VoiceClient.__init__ raises before a single packet is sent - so on the ARM setup the
    gate answered "yes, voice works" and the failure then surfaced as a raw RuntimeError partway
    through a grind, which is exactly what this gate exists to prevent."""
    import builtins
    import voice_player

    real_import = builtins.__import__

    def no_davey(name, *a, **kw):
        if name == "davey":
            raise ImportError("no ARM build")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_davey)
    assert voice_player.voice_supported() is False
    reason = voice_player.voice_unavailable_reason() or ""
    assert "davey" in reason
    assert "Intel" in reason, "the reason must name the fix, not just the missing piece"


def test_when_both_libraries_are_there_the_gate_opens_and_gives_no_reason():
    """Skipped on the ARM environment, where davey is genuinely absent - the suite has to pass in
    BOTH environments, and asserting "voice is available" where it truthfully is not would be a
    test that lies in exactly the way this gate was just fixed for."""
    import pytest
    import voice_player

    if voice_player.voice_unavailable_reason() is not None:
        pytest.skip("ARM environment: davey is genuinely missing, which is the honest answer here")
    assert voice_player.voice_supported() is True
