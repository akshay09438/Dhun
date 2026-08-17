"""`/add` and `/mine` — the Discord half of bring-your-own-song.

The bot does NO ingesting. It has no numpy, no Replicate and no ffmpeg, and a second copy of that
pipeline here is exactly how uploads would start behaving differently from catalogue songs — the
kind of drift nobody notices until a tester complains. So these tests are about the things the BOT
is actually responsible for:

  * handing the bytes to the engine with the right fields, and nothing else
  * saying no to a beat with no drop before spending a round trip
  * showing the engine's own refusal wording, unchanged — it is written for a person to read
  * carrying the grind on the reply, because an upload never enters the 25-slot `/grind` menu and
    would otherwise exist and be unreachable
  * putting the BEAT in slot 1 and the VOCAL in slot 2 whichever side was uploaded
  * letting somebody mix two of their OWN uploads, which is a supported thing to want
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot as botmod  # noqa: E402
from api_client import EngineError, PromptDJClient, Song  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    botmod._my_upload_ids.clear()
    yield
    botmod._my_upload_ids.clear()


def _song(sid, name, role, featured=True):
    return Song(id=sid, name=name, role_hint=role, language="english", featured=featured)


# --- what the reply offers to mix with ------------------------------------------------------

def test_a_vocal_upload_is_offered_beats():
    botmod.bot.songs = [_song("b" * 64, "Levels", "beat"), _song("v" * 64, "Location", "vocals")]
    opts = botmod._partner_options("111", "beat")
    assert [o.label for o in opts] == ["Levels"]


def test_a_beat_upload_is_offered_vocals():
    botmod.bot.songs = [_song("b" * 64, "Levels", "beat"), _song("v" * 64, "Location", "vocals")]
    opts = botmod._partner_options("111", "vocals")
    assert [o.label for o in opts] == ["Location"]


def test_your_own_uploads_come_first_and_are_labelled():
    """Mixing two of your OWN songs is supported, and invisible unless the list puts it in front."""
    botmod.bot.songs = [_song("c" * 64, "Catalogue Beat", "beat"),
                        _song("m" * 64, "My Own Beat", "beat", featured=False)]
    botmod._my_upload_ids["111"] = {"m" * 64}
    opts = botmod._partner_options("111", "beat")
    assert opts[0].label == "My Own Beat"
    assert opts[0].description == "your upload"
    assert [o.label for o in opts] == ["My Own Beat", "Catalogue Beat"]


def test_a_stranger_does_not_see_your_uploads_as_theirs():
    botmod.bot.songs = [_song("m" * 64, "My Own Beat", "beat", featured=False)]
    botmod._my_upload_ids["111"] = {"m" * 64}
    assert botmod._partner_options("222", "beat") == []


def test_the_partner_list_never_widens_the_curated_menu():
    """An unfeatured catalogue song stays out — /add is not a back door to the other 87."""
    botmod.bot.songs = [_song("x" * 64, "Not On The Menu", "beat", featured=False)]
    assert botmod._partner_options("111", "beat") == []


def test_the_partner_list_fits_discords_limit():
    botmod.bot.songs = [_song(f"{i:064x}", f"Beat {i}", "beat") for i in range(60)]
    assert len(botmod._partner_options("111", "beat")) <= 25


# --- which side goes where ------------------------------------------------------------------

class _FakeInteraction:
    """Just enough of a Discord interaction for the view to run against."""

    def __init__(self, uid=111):
        self.user = type("U", (), {"id": uid, "name": "someone", "display_name": "Someone"})()
        self.edited = False
        self.said = None
        outer = self

        class _Resp:
            async def edit_message(self, **_k):
                outer.edited = True

            async def send_message(self, msg, **_k):
                outer.said = msg

        self.response = _Resp()


def _pairs_from(role: str, uploaded_id: str, partner_id: str, monkeypatch, uid=111,
                owner=111) -> list:
    """Run the picker callback and report the pair it handed to the grinder."""
    seen = {}

    class FakeCtx:
        def __init__(self, interaction, pairs, **k):
            seen["pairs"] = pairs

        async def run(self, first):
            seen["ran"] = True

    monkeypatch.setattr(botmod, "GrindContext", FakeCtx)
    view = botmod.UploadedSongView(owner, uploaded_id, role)
    asyncio.run(view.start(_FakeInteraction(uid), partner_id))
    return seen


def test_an_uploaded_beat_goes_in_slot_one(monkeypatch):
    botmod.bot.songs = [_song("v" * 64, "Location", "vocals")]
    seen = _pairs_from("beat", "u" * 64, "v" * 64, monkeypatch)
    assert seen["pairs"] == [("u" * 64, "v" * 64)], "an uploaded beat must be song1"
    assert seen.get("ran")


def test_an_uploaded_vocal_goes_in_slot_two(monkeypatch):
    botmod.bot.songs = [_song("b" * 64, "Levels", "beat")]
    seen = _pairs_from("vocals", "u" * 64, "b" * 64, monkeypatch)
    assert seen["pairs"] == [("b" * 64, "u" * 64)], "an uploaded vocal must be song2"


def test_somebody_else_cannot_grind_your_upload(monkeypatch):
    botmod.bot.songs = [_song("b" * 64, "Levels", "beat")]
    seen = _pairs_from("vocals", "u" * 64, "b" * 64, monkeypatch, uid=222, owner=111)
    assert "pairs" not in seen, "a stranger started somebody else's grind"


def test_the_reply_carries_a_grind_because_uploads_are_not_in_the_menu():
    """An upload never enters the 25-slot /grind picker. Without this control the song would be
    ingested, paid for, and unreachable."""
    botmod.bot.songs = [_song("b" * 64, "Levels", "beat")]
    view = botmod.UploadedSongView(111, "u" * 64, "vocals")
    assert view.children, "the reply offers no way to actually mix the song"


# --- the client contract --------------------------------------------------------------------

def test_the_upload_is_sent_with_who_role_and_drop():
    sent = {}

    class FakeClient:
        async def post(self, url, files=None, data=None, timeout=None):
            sent.update({"url": url, "files": files, "data": data})
            return type("R", (), {"status_code": 200,
                                  "json": lambda self: {"song_id": "a" * 64}})()

    c = PromptDJClient.__new__(PromptDJClient)
    c._client = FakeClient()
    asyncio.run(c.add_song(b"bytes", "my song.mp3", uploaded_by="111", role="beat",
                           main_drop="1:24", display_name="my song"))
    assert sent["url"] == "/songs/add"
    assert sent["data"]["uploaded_by"] == "111"
    assert sent["data"]["role"] == "beat"
    assert sent["data"]["main_drop"] == "1:24"
    assert "file" in sent["files"]


def test_an_engine_refusal_is_raised_for_the_card_to_show_verbatim():
    """The engine's refusals are written to be read by a person. Rewrapping them in the bot would
    mean two places to keep true, and the bot's copy would drift."""
    class FakeClient:
        async def post(self, *a, **k):
            return type("R", (), {"status_code": 400, "headers": {},
                                  "json": lambda self: {"detail": "That's over 8 minutes."},
                                  "text": "That's over 8 minutes."})()

    c = PromptDJClient.__new__(PromptDJClient)
    c._client = FakeClient()
    with pytest.raises(EngineError) as e:
        asyncio.run(c.add_song(b"x", "x.mp3", uploaded_by="1", role="vocals"))
    assert "8 minutes" in str(e.value)


def test_progress_is_reported_only_when_the_stage_changes():
    """The card is edited on a real change, not on every poll — Discord rate-limits edits, and a
    card that rewrites itself every two seconds reads as broken."""
    stages = ["separating the parts", "separating the parts", "working out the beat and the key"]
    shown = []

    class FakeClient:
        def __init__(self):
            self.i = 0

        async def get(self, url):
            i = min(self.i, len(stages) - 1)
            self.i += 1
            done = self.i >= len(stages)
            return type("R", (), {"status_code": 200,
                                  "json": lambda self: {"stage": stages[i], "done": done}})()

    async def note(text):
        shown.append(text)

    c = PromptDJClient.__new__(PromptDJClient)
    c._client = FakeClient()
    asyncio.run(c.wait_for_add("a" * 64, poll=0, on_stage=note))
    assert shown == ["separating the parts", "working out the beat and the key"], (
        "the card was edited on every poll rather than on a real change")
