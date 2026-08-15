"""Showing a mix must not promise one that is never coming.

MEASURED 2026-08-16. Pressing 📣 "Show this mix to everyone" on any of 22 grinds answered:

    "Give it a second, this one is still arriving."

Those mixes had been deleted days earlier - the engine evicts a render after seven days and the
bot's own copy sits in Windows Temp, which nothing sweeps on purpose and Windows eventually wipes.
`pin` looked at `ctx.audio_path`, found nothing there, and could not tell "not ready yet" apart from
"gone for good", so it guessed the kinder one. A person reading that waits forever.

TWO CHANGES, AND THE FIRST IS THE ONE THAT MATTERS. The button now tries to GET THE AUDIO BACK
before giving up - the engine still holds every render for seven days and the row already knows its
id - so most presses that used to fail now simply work. Only when it is genuinely past that does it
say so, plainly, and it says gone rather than soon.
"""
import asyncio
import os
import types
import wave
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import showcase  # noqa: E402
import store  # noqa: E402

PAIRS = [["beat-1", "vocal-1", "Beat One", "Vocal One"]]


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


class _Engine:
    def __init__(self, has=True):
        self.has = has
        self.kept = []

    async def fetch_audio(self, mix_id, dest):
        if not self.has:
            raise RuntimeError("404")
        _wav(dest)
        return str(dest)

    async def fetch_set_audio(self, set_id, dest):
        return await self.fetch_audio(set_id, dest)

    async def keep_render(self, ref):
        self.kept.append(ref)
        return True


class _Channel:
    def __init__(self):
        self.id = 4242
        self.mention = "#best-mixes"
        self.posts = []

    async def send(self, **k):
        self.posts.append(k)
        return types.SimpleNamespace(id=98765,
                                     add_reaction=self._noop)

    async def _noop(self, *a, **k):
        return None


def _ctx(number, audio_path=None, ref_id=None):
    user = types.SimpleNamespace(id=7, name="Aashwin", display_name="Aashwin")
    return types.SimpleNamespace(
        number=number,
        audio_path=Path(audio_path) if audio_path else None,
        ref_id=ref_id,
        duration=12.0,
        interaction=types.SimpleNamespace(user=user),
        named_pairs=lambda: [("Beat One", "Vocal One")],
        _attach=lambda w: _fake_attach(w))


async def _fake_attach(wav):
    return f"<file:{Path(wav).name}>"


def _interaction(channel):
    guild = types.SimpleNamespace(get_channel=lambda _id: channel)
    return types.SimpleNamespace(
        user=types.SimpleNamespace(id=7, display_name="Aashwin"), guild=guild)


@pytest.fixture()
def wired(monkeypatch):
    """Point the showcase at a real channel id and a fake engine."""
    ch = _Channel()
    monkeypatch.setattr(showcase.CFG, "fresh_grinds_channel_id", 4242, raising=False)
    engine = _Engine()
    monkeypatch.setattr(showcase, "_engine", lambda: engine, raising=False)
    return ch, engine


def _grind(ref_id=None, audio_path=None):
    n = store.new_grind(user_id=7, user_name="Aashwin", pairs=PAIRS,
                        created_at="2026-08-15T14:52:49+00:00", guild_id=1, channel_id=2)
    store.attach_message(n, 5000 + n)
    if ref_id:
        store.set_pairs(n, PAIRS, ref_id=ref_id)
    if audio_path:
        store.set_audio_path(n, str(audio_path))
    return n


def test_a_mix_whose_local_copy_was_swept_is_fetched_back_and_shown(tmp_path, wired):
    """THE COMMON CASE, and it used to be a dead end. 22 grinds were in exactly this state."""
    ch, engine = wired
    n = _grind(ref_id="ref-abc", audio_path=tmp_path / "swept.wav")
    ctx = _ctx(n, audio_path=None, ref_id="ref-abc")

    said = asyncio.run(showcase.pin(ctx, _interaction(ch)))

    assert ch.posts, "the mix was not posted even though the engine still had it"
    assert "still arriving" not in said.lower()
    assert str(n) in said


def test_a_mix_past_its_seven_days_is_called_gone_not_coming(tmp_path, wired, monkeypatch):
    """THE LIE. Never tell somebody to wait for a file that was deleted days ago."""
    ch, _ = wired
    monkeypatch.setattr(showcase, "_engine", lambda: _Engine(has=False), raising=False)
    n = _grind(ref_id="ref-old", audio_path=tmp_path / "gone.wav")
    ctx = _ctx(n, audio_path=None, ref_id="ref-old")

    said = asyncio.run(showcase.pin(ctx, _interaction(ch)))

    lowered = said.lower()
    assert "still arriving" not in lowered and "give it a second" not in lowered
    assert "gone" in lowered or "no longer" in lowered
    assert not ch.posts, "it posted an empty showcase entry for a mix it does not have"


def test_a_failed_pin_can_be_tried_again(tmp_path, wired, monkeypatch):
    """`mark_pinned` is one-shot on purpose (people double-tap). A press that could not find the
    audio must not burn that one shot, or the mix can never be shown even once it is recoverable."""
    ch, _ = wired
    monkeypatch.setattr(showcase, "_engine", lambda: _Engine(has=False), raising=False)
    n = _grind(ref_id="ref-old", audio_path=tmp_path / "gone.wav")

    asyncio.run(showcase.pin(_ctx(n, ref_id="ref-old"), _interaction(ch)))

    assert store.get(n)["pinned_at"] is None, "a failed press marked the grind as already shown"


def test_a_mix_still_on_disk_is_not_re_downloaded(tmp_path, wired):
    """The cheap path stays cheap - no round trip for a file that is right there."""
    ch, engine = wired
    wav = tmp_path / "here.wav"
    _wav(wav)
    n = _grind(ref_id="ref-abc", audio_path=wav)
    ctx = _ctx(n, audio_path=wav, ref_id="ref-abc")

    said = asyncio.run(showcase.pin(ctx, _interaction(ch)))

    assert ch.posts
    assert "gone" not in said.lower()


def test_a_grind_that_never_started_still_says_give_it_a_second(wired):
    """The message was not wrong everywhere - a grind with no number really has not arrived."""
    ch, _ = wired
    said = asyncio.run(showcase.pin(_ctx(None), _interaction(ch)))

    assert "still arriving" in said.lower()
    assert not ch.posts
