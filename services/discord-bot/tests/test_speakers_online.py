"""Logging the extra identities in - and what happens when one of them will not come.

WHY THIS IS TESTED AT ALL. Three ways an extra voice fails to arrive, and every one of them is
something the founder can plausibly do by accident: paste a token that has since been reset, create
the application but never invite it to the server, or paste a token whose bot user was never made.
None of those may cost anything more than one line in the log. A second Grinder that fails to log in
and takes the FIRST one down with it would turn "one room has sound" into "no room has sound", which
is very much worse than the problem being solved.

The client is injected, so this runs with no Discord at all. What it cannot prove is that a real
token logs in - that needs the founder's own token and their own server.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import speakers  # noqa: E402


class FakeClient:
    """A login that behaves like discord.Client in the one way that matters: `start` never returns
    while it is healthy, and `wait_until_ready` completes once it is up."""

    def __init__(self, *, fails=None, never_ready=False):
        self.fails = fails
        self.never_ready = never_ready
        self.closed = False
        self._ready = asyncio.Event()

    async def start(self, token):
        if self.fails is not None:
            raise self.fails
        if not self.never_ready:
            self._ready.set()
        await asyncio.Event().wait()        # a healthy login runs for the life of the process

    async def wait_until_ready(self):
        await self._ready.wait()

    async def close(self):
        self.closed = True


def _pool(n):
    return speakers.SpeakerPool([f"tok-{i}" for i in range(n)])


def _run(pool, clients, **kw):
    it = iter(clients)
    return asyncio.run(speakers.bring_online(pool, lambda: next(it), ready_timeout=0.2, **kw))


def test_a_healthy_extra_comes_online_and_keeps_its_client():
    pool = _pool(1)
    client = FakeClient()
    live = _run(pool, [client])
    assert len(live) == 1
    assert live[0].client is client
    assert pool.speakers == live


def test_a_token_that_will_not_log_in_is_dropped_not_fatal():
    """The commonest real failure: a token that was reset in the Developer Portal after being
    pasted. It must cost one log line and nothing else."""
    pool = _pool(1)
    bad = FakeClient(fails=RuntimeError("Improper token has been passed"))
    live = _run(pool, [bad])
    assert live == []
    assert pool.speakers == [], "a dead identity must not sit in the pool pretending to hold rooms"
    assert bad.closed is True, "and it must not leak a half-open connection"


def test_one_bad_token_does_not_stop_the_good_ones():
    """THE POINT OF ALL THIS. A second Grinder that fails must never cost the community the first."""
    pool = _pool(3)
    good_a, bad, good_b = FakeClient(), FakeClient(fails=RuntimeError("nope")), FakeClient()
    live = _run(pool, [good_a, bad, good_b])
    assert [s.client for s in live] == [good_a, good_b]


def test_an_identity_that_never_becomes_ready_is_dropped():
    """Invited nowhere, or sitting behind a broken network. Waiting forever at startup would stop
    the bot ever coming up at all, which is the worst possible trade."""
    pool = _pool(1)
    stuck = FakeClient(never_ready=True)
    assert _run(pool, [stuck]) == []
    assert stuck.closed is True


def test_no_extra_tokens_means_no_clients_are_even_made():
    """The default. Nothing is created, nothing is logged in, nothing can fail."""
    made = []

    def factory():
        made.append(1)
        return FakeClient()

    pool = _pool(0)
    assert asyncio.run(speakers.bring_online(pool, factory)) == []
    assert made == []


def test_each_live_identity_gets_its_finishing_touches():
    """Where the avatar is applied, so the second Grinder wears the same face with no work from the
    founder. It runs per identity and only for the ones that actually came up."""
    pool = _pool(2)
    good, bad = FakeClient(), FakeClient(fails=RuntimeError("nope"))
    touched = []

    async def on_ready(s):
        touched.append(s.index)

    _run(pool, [good, bad], on_ready=on_ready)
    assert touched == [1], "only the identity that came online"


# --- the identical twin: same face, no manual work ------------------------------------------------
# The founder's call. Somebody in the second room just sees Grinder and never learns there are two,
# so the picture is applied from code rather than being one more job in the Developer Portal.

class _FakeUser:
    def __init__(self, uid=555, avatar=None):
        self.id = uid
        self.avatar = avatar
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


def _fake_bot(cleared):
    import bot as botmod

    async def clear(client=None):
        cleared.append(client)

    return type("S", (), {"_clear_stale_voice": staticmethod(clear),
                          "_set_up_extra_voice": botmod.PromptDJBot._set_up_extra_voice})()


def _speaker_with(user):
    s = speakers.Speaker(1, "tok")
    s.client = type("C", (), {"user": user})()
    return s


def test_an_extra_gets_the_same_disc_as_the_main_grinder(monkeypatch, tmp_path):
    import bot as botmod

    monkeypatch.setattr(botmod.brand, "image_bytes", lambda _p: b"PNGDATA")
    monkeypatch.setattr(botmod.brand, "slot_needs_upload", lambda _slot: True)
    marked = []
    monkeypatch.setattr(botmod.brand, "mark_slot_applied", marked.append)

    user = _FakeUser()
    cleared = []
    asyncio.run(_fake_bot(cleared)._set_up_extra_voice(_speaker_with(user)))

    assert user.edits == [{"avatar": b"PNGDATA"}], "the extra must wear the same face"
    assert marked == ["avatar-555"], "and remember it did, PER IDENTITY - the limit is per bot"


def test_an_extra_whose_picture_is_already_right_is_left_alone(monkeypatch):
    """Discord's avatar rate limit is strict and counted per bot. Re-uploading an identical picture
    on every restart would spend it for nothing."""
    import bot as botmod

    monkeypatch.setattr(botmod.brand, "slot_needs_upload", lambda _slot: False)
    monkeypatch.setattr(botmod.brand, "image_bytes",
                        lambda _p: (_ for _ in ()).throw(AssertionError("must not read the art")))

    user = _FakeUser(avatar="already-set")
    asyncio.run(_fake_bot([])._set_up_extra_voice(_speaker_with(user)))
    assert user.edits == []


def test_an_extra_has_its_own_zombie_voice_session_cleared(monkeypatch):
    """Each identity holds its OWN voice session, so each can leave its own zombie behind when the
    bot is killed. A stale session on the second Grinder presents as 'the second room never plays' -
    indistinguishable from the whole feature not working."""
    import bot as botmod

    monkeypatch.setattr(botmod.brand, "slot_needs_upload", lambda _slot: False)
    cleared = []
    speaker = _speaker_with(_FakeUser(avatar="x"))
    asyncio.run(_fake_bot(cleared)._set_up_extra_voice(speaker))
    assert cleared == [speaker.client], "the EXTRA's session, not the main bot's"


def test_a_failure_while_branding_an_extra_does_not_drop_it():
    """Branding is cosmetic. An identity that is logged in and can hold a room must keep holding it
    even if its picture could not be set."""
    pool = _pool(1)

    async def on_ready(s):
        raise RuntimeError("avatar rate limited")

    live = _run(pool, [FakeClient()], on_ready=on_ready)
    assert len(live) == 1, "a cosmetic failure must not cost a room its sound"
