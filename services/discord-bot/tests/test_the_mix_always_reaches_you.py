"""The finished mix has to REACH the person who made it, not merely be shown to them once.

WHAT WAS WRONG, PROVEN AGAINST DISCORD 2026-08-16. A grind card is an ephemeral message, and
Discord does not store those anywhere. Asking Discord for the two cards Aashwin lost, by id:

    grind #33   NOT IN THE CHANNEL - Discord never stored it
    grind #39   NOT IN THE CHANNEL - Discord never stored it

The bot had done everything right both times - rendered, transcoded, attached, edited the card. He
closed the app, and the only copy he had ceased to exist. 38 of the 39 grinds ever made were in
that position; exactly one had a permanent copy, because somebody pressed 📣.

WHY /mygrinds WAS NOT ENOUGH (founder, 2026-08-16): "I want a system where the song has to be sent
to the user by hook or by crook. I don't want users to go to /mygrinds and find their last song."
Recovery asks the person to know a command and think to use it, at the exact moment they have
concluded the product lost their work. The mix has to arrive somewhere that KEEPS it, by itself.

THE ROUTE THAT KEEPS THINGS. A direct message is exactly as private as an ephemeral card - nobody
else can see it - and Discord stores it forever, on every device that person owns. So the mix is
DM'd, and the card keeps its copy too: the card is where they are looking now, the DM is the copy
that is still there next month.

BY HOOK OR BY CROOK means the ladder is honest about what it cannot do:
  * a transient failure is RETRIED rather than shrugged off
  * DMs switched off is permanent, so it is not retried - it is EXPLAINED, on the card, with the
    one thing they can change
  * nothing about delivery is ever allowed to lose the grind itself
"""
import asyncio
import os
import types
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import discord  # noqa: E402

import deliver  # noqa: E402
import store  # noqa: E402

PAIRS = [["beat-1", "vocal-1", "Wake Me Up (Avicii)", "Circles (Post Malone)"]]


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


async def _attach(wav):
    return f"<file:{Path(wav).name}>"


async def _too_big(_wav):
    return None


def _forbidden():
    """The real exception Discord raises when somebody has DMs from server members switched off."""
    resp = types.SimpleNamespace(status=403, reason="Forbidden")
    return discord.Forbidden(resp, "Cannot send messages to this user")


class FakeUser:
    """Somebody with a direct-message channel, which is where a kept copy has to land."""

    def __init__(self, *, fails_with=None, fail_times=0):
        self.id = 753904247518658650
        self.display_name = "Aashwin"
        self.dm_channel = None
        self.sent = []
        self._fails_with = fails_with
        self._fail_times = fail_times
        self.dms_created = 0

    async def create_dm(self):
        self.dms_created += 1
        self.dm_channel = self
        return self

    async def send(self, content=None, file=None, **k):
        if self._fail_times > 0:
            self._fail_times -= 1
            raise self._fails_with
        self.sent.append({"content": content, "file": file})
        return types.SimpleNamespace(id=999)


def _wav(tmp_path):
    p = tmp_path / "finished.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 128)
    return p


# --- the mix must arrive somewhere Discord keeps -------------------------------------------------

def test_the_mix_is_sent_to_the_person_who_made_it(tmp_path):
    """THE WHOLE POINT. Nobody should have to ask for their own song."""
    user = FakeUser()

    ok, note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert ok is True
    assert len(user.sent) == 1, "the mix was never sent to them"
    assert user.sent[0]["file"] is not None, "a message arrived with no music in it"


def test_it_opens_a_direct_message_rather_than_posting_in_a_room(tmp_path):
    """Private stays private. The reason the card was ephemeral in the first place was that the
    room was filling with everybody else's music - a DM keeps that property and adds permanence."""
    user = FakeUser()

    asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert user.dms_created == 1


def test_the_note_tells_them_where_it_went(tmp_path):
    """They are looking at the card, not their inbox. If nothing says the copy exists, the copy
    might as well not."""
    user = FakeUser()

    _ok, note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert note, "nothing on the card mentions the copy that was sent"
    lowered = note.lower()
    assert "message" in lowered or "dm" in lowered or "inbox" in lowered


# --- by hook or by crook: what happens when the route is blocked ----------------------------------

def test_a_transient_failure_is_retried_not_shrugged_off(tmp_path):
    """Discord hiccups. One flake must not cost somebody their song."""
    user = FakeUser(fails_with=RuntimeError("Discord is having a bad day"), fail_times=1)

    ok, _note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert ok is True, "it gave up after a single transient error"
    assert len(user.sent) == 1


def test_dms_switched_off_is_explained_rather_than_retried(tmp_path):
    """Forbidden is permanent - retrying it just wastes time and still fails. What matters is that
    the person is told, in words they can act on, instead of silently keeping nothing."""
    user = FakeUser(fails_with=_forbidden(), fail_times=99)

    ok, note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert ok is False
    assert user.dms_created == 1, "it kept retrying something that can never succeed"
    lowered = note.lower()
    assert "direct message" in lowered or "dms" in lowered, note
    assert "reload" in lowered or "disappear" in lowered or "keep" in lowered, (
        "it does not tell them what they stand to lose")


def test_a_mix_too_big_to_send_says_so_and_does_not_claim_success(tmp_path):
    user = FakeUser()

    ok, note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _too_big))

    assert ok is False
    assert user.sent == []
    assert "big" in note.lower() or "long" in note.lower()


def test_delivery_never_raises_whatever_discord_does(tmp_path):
    """A finished mix must never be lost to a failure in the act of handing it over."""
    user = FakeUser(fails_with=RuntimeError("boom"), fail_times=99)

    ok, note = asyncio.run(deliver.to_the_maker(user, 39, _wav(tmp_path), _attach))

    assert ok is False
    assert note, "it failed silently"


# --- and the card must still carry it too ---------------------------------------------------------

class _Message:
    def __init__(self):
        self.edits = []

    async def edit(self, **k):
        self.edits.append(k)


class _Api:
    async def start_mix(self, a, b, user_id, generation=0, user_name=None):
        return "mix-1"

    async def wait_for_mix(self, mix_id, on_progress=None):
        return types.SimpleNamespace(status="ready", message=None, rule=1)

    async def fetch_audio(self, mix_id, dest):
        import wave
        with wave.open(str(dest), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 8000)
        return str(dest)


@pytest.fixture()
def wired(monkeypatch):
    import bot as botmod
    monkeypatch.setattr(botmod.bot, "api", _Api(), raising=False)
    monkeypatch.setattr(botmod, "_attachment_for", lambda w, number: _attach(w))
    sent = {}

    async def _fake_deliver(user, number, wav, attach):
        sent["called"] = {"user": user, "number": number, "wav": wav}
        return True, "Sent to your messages."
    monkeypatch.setattr(botmod.deliver, "to_the_maker", _fake_deliver)
    return botmod, sent


def _ctx(botmod, user):
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None)
    ctx = botmod.GrindContext(interaction, [("beat-1", "vocal-1")])
    ctx.number = store.new_grind(user_id=user.id, user_name="Aashwin", pairs=PAIRS,
                                 created_at="2026-08-16T00:00:00+00:00")
    store.attach_message(ctx.number, 5000)
    ctx.message = _Message()
    return ctx


def test_a_finished_grind_hands_the_mix_over_by_both_routes(wired):
    """The card is where they are looking now; the DM is the copy still there next month. A fix
    that moved the mix OUT of the card would trade one loss for another."""
    botmod, sent = wired
    user = FakeUser()
    ctx = _ctx(botmod, user)

    asyncio.run(ctx.run(first=False))

    assert sent.get("called"), "the finished mix was never sent to the person who made it"
    assert sent["called"]["number"] == ctx.number
    assert any(e.get("attachments") for e in ctx.message.edits), \
        "the card no longer carries the mix"


def test_the_grind_survives_a_delivery_that_fails(wired, monkeypatch):
    """Recording where the audio lives is what makes it recoverable at all. A delivery failure
    must never cost that."""
    botmod, _sent = wired

    async def _boom(*a, **k):
        raise RuntimeError("delivery exploded")
    monkeypatch.setattr(botmod.deliver, "to_the_maker", _boom)
    user = FakeUser()
    ctx = _ctx(botmod, user)

    asyncio.run(ctx.run(first=False))

    assert store.get(ctx.number)["audio_path"], \
        "a failed hand-over lost the record of where the mix is"
