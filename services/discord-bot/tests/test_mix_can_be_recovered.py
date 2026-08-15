"""A finished mix must be recoverable after its card is gone.

WHAT THE FOUNDER SAW, 2026-08-15. Aashwin ran two grinds. The first one rendered fine and its MP3
was attached to his card - and he still ended up with nothing, because a grind card is EPHEMERAL:
Discord deletes it the moment that person reloads their client, and gives no way to fetch it back.

MEASURED THE NEXT MORNING, across every grind ever made: 23 of 38 (60%) could no longer be played
by anybody. Three layers each throw the audio away by design, and only one keeps it:

  * the card              - ephemeral, dies on a client reload
  * the bot's copy        - lives in Windows Temp, which the engine's janitor never sweeps and
                            Windows eventually wipes
  * the engine's copy     - deliberately evicted after 7 days, or sooner under disk pressure
  * a 📣 showcase post    - PERMANENT, and the only durable copy there is

Exactly ONE grind out of 38 had ever been showcased. So the normal outcome for a mix is that it
disappears, `/mygrinds` lists it by name with no way to hear it, and 🔁 Again deliberately makes a
DIFFERENT take rather than the one that was lost.

THE FIX IS A DRAWER, NOT NEW STORAGE. The engine already keeps every render for seven days and the
grind row already stores its `ref_id`, so the audio can simply be asked for again - no re-render, no
new file kept anywhere, and the fetch re-stamps the render as recently used so it stops being the
next thing evicted. When it truly is past seven days, say so plainly instead of pretending.
"""
import asyncio
import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import recall  # noqa: E402
import store  # noqa: E402

SINGLE = [["beat-1", "vocal-1", "Beat One", "Vocal One"]]
SET = [["beat-1", "vocal-1", "Beat One", "Vocal One"],
       ["beat-2", "vocal-2", "Beat Two", "Vocal Two"]]


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


class FakeEngine:
    """Stands in for the engine's two audio routes. Records what was asked for so a test can prove
    a SET is fetched through the set route rather than the mix route."""

    def __init__(self, *, has: bool = True, payload: bytes = b"RIFFfake-audio-bytes"):
        self.has = has
        self.payload = payload
        self.mix_calls: list[str] = []
        self.set_calls: list[str] = []

    async def fetch_audio(self, mix_id, dest_path):
        self.mix_calls.append(mix_id)
        return self._write(dest_path)

    async def fetch_set_audio(self, set_id, dest_path):
        self.set_calls.append(set_id)
        return self._write(dest_path)

    def _write(self, dest_path):
        if not self.has:
            raise RuntimeError("404 - the engine no longer has this render")
        Path(dest_path).write_bytes(self.payload)
        return str(dest_path)


def _grind(pairs=SINGLE, *, ref_id=None, audio_path=None):
    n = store.new_grind(user_id=7, user_name="Aashwin", pairs=pairs,
                        created_at="2026-08-15T14:52:49+00:00", guild_id=1, channel_id=2)
    # Production attaches the card's message id immediately after creating the row, and
    # `recent_for_user` only lists grinds that have one - so a helper that skips it builds rows
    # `/mygrinds` would never show.
    store.attach_message(n, 5000 + n)
    if ref_id:
        store.set_pairs(n, pairs, ref_id=ref_id)
    if audio_path:
        store.set_audio_path(n, str(audio_path))
    return n


def test_uses_the_local_file_when_it_is_still_there(tmp_path):
    """No re-download when the copy on disk survives - that is the fast, free path."""
    wav = tmp_path / "grind_local.wav"
    wav.write_bytes(b"RIFFstill-here")
    n = _grind(ref_id="ref-abc", audio_path=wav)
    engine = FakeEngine()

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert got == wav
    assert engine.mix_calls == [], "it re-downloaded a file it already had"


def test_fetches_it_back_from_the_engine_when_the_local_copy_is_gone(tmp_path):
    """THE AASHWIN CASE. The card is gone and Temp has been wiped, but the engine still has it."""
    missing = tmp_path / "swept-away.wav"
    n = _grind(ref_id="ref-abc", audio_path=missing)
    engine = FakeEngine()

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert got is not None and got.exists()
    assert got.read_bytes() == b"RIFFfake-audio-bytes"
    assert engine.mix_calls == ["ref-abc"]


def test_remembers_where_it_put_the_recovered_file(tmp_path):
    """Recovering once should make the next recovery free, not download it again."""
    n = _grind(ref_id="ref-abc", audio_path=tmp_path / "gone.wav")
    engine = FakeEngine()

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert store.get(n)["audio_path"] == str(got)


def test_a_set_is_fetched_through_the_set_route(tmp_path):
    """A multi-pair grind is ONE joined file and only the set route serves it - asking the mix
    route for a set id returns nothing."""
    n = _grind(SET, ref_id="set-xyz", audio_path=tmp_path / "gone.wav")
    engine = FakeEngine()

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert got is not None and got.exists()
    assert engine.set_calls == ["set-xyz"]
    assert engine.mix_calls == []


def test_says_nothing_rather_than_lying_when_the_render_is_past_its_seven_days(tmp_path):
    """The honest end of the road: gone locally AND evicted upstream."""
    n = _grind(ref_id="ref-old", audio_path=tmp_path / "gone.wav")
    engine = FakeEngine(has=False)

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert got is None


def test_a_grind_with_no_reference_cannot_be_recovered(tmp_path):
    """Aashwin's SECOND mix: the bot was killed mid-render so the row never learned the ref_id.
    Nothing to ask the engine for, and no pretending otherwise."""
    n = _grind(ref_id=None, audio_path=None)
    engine = FakeEngine()

    got = asyncio.run(recall.audio_for(store.get(n), engine))

    assert got is None
    assert engine.mix_calls == [] and engine.set_calls == []


# --- what the person is actually handed ---------------------------------------------------------
# The sentence matters as much as the file. `showcase.pin` used to answer "Give it a second, this
# one is still arriving" for a mix deleted days earlier, so somebody would wait for something that
# was never coming. Gone has to read as gone.

async def _stub_attach(wav):
    """Stands in for the real transcode. Kept out of these tests on purpose: ffmpeg on a
    handful of fake bytes proves nothing about whether the right sentence comes back."""
    return f"<file:{Path(wav).name}>"


def test_hands_back_a_file_and_names_the_grind(tmp_path):
    wav = tmp_path / "there.wav"
    wav.write_bytes(b"RIFFstill-here")
    n = _grind(ref_id="ref-abc", audio_path=wav)

    got, said = asyncio.run(recall.recovered_file(store.get(n), FakeEngine(), _stub_attach))

    assert got is not None
    assert f"#{n}" in said


def test_says_it_is_gone_and_never_says_it_is_still_coming(tmp_path):
    """THE FIX FOR THE MISLEADING LINE. 22 grinds were in this state on 2026-08-16."""
    n = _grind(ref_id="ref-old", audio_path=tmp_path / "gone.wav")

    got, said = asyncio.run(
        recall.recovered_file(store.get(n), FakeEngine(has=False), _stub_attach))

    assert got is None
    lowered = said.lower()
    assert "arriving" not in lowered and "give it a second" not in lowered
    assert "gone" in lowered or "no longer" in lowered
    assert "again" in lowered, "it should offer the next best thing rather than dead-ending"


def test_the_transcode_is_not_written_twice(tmp_path):
    """`GrindContext._attach` and the recovery picker must share ONE transcoder. Two copies of
    "try 160k, then 128k, then 96k, then 64k" drift, and the one nobody is looking at is the one
    that ends up handing somebody a file Discord refuses."""
    import inspect

    import bot as botmod
    src = inspect.getsource(botmod.GrindContext._attach)
    assert "libmp3lame" not in src and "160k" not in src, (
        "_attach still has its own copy of the bitrate ladder instead of calling the shared one")


def test_a_mix_too_big_to_attach_is_not_reported_as_lost(tmp_path):
    """A transcode that cannot fit Discord's limit is a DIFFERENT problem from an evicted render,
    and telling somebody their mix is gone when it is sitting right there would be a lie."""
    wav = tmp_path / "huge.wav"
    wav.write_bytes(b"RIFFenormous")
    n = _grind(ref_id="ref-abc", audio_path=wav)

    async def _too_big(_w):
        return None

    got, said = asyncio.run(recall.recovered_file(store.get(n), FakeEngine(), _too_big))

    assert got is None
    assert "gone" not in said.lower()
    assert "big" in said.lower() or "long" in said.lower()


# --- /mygrinds: the drawer people can actually open ----------------------------------------------

def _interaction(user_id=7):
    sent = {}

    class _Resp:
        def __init__(self):
            self._done = False

        def is_done(self):
            return self._done

        async def defer(self, **k):
            self._done = True

        async def send_message(self, *a, **k):
            self._done = True
            sent["msg"] = a[0] if a else k.get("content")
            sent["ephemeral"] = k.get("ephemeral")
            sent["view"] = k.get("view")
            sent["embed"] = k.get("embed")

    class _Follow:
        async def send(self, *a, **k):
            sent.setdefault("followups", []).append(
                {"content": a[0] if a else k.get("content"),
                 "file": k.get("file"), "ephemeral": k.get("ephemeral")})

    import types
    i = types.SimpleNamespace(
        user=types.SimpleNamespace(id=user_id, name="t", display_name="t"),
        response=_Resp(), followup=_Follow(), guild=None, channel=None)
    return i, sent


def test_the_picker_lists_every_grind_by_number(tmp_path):
    import bot as botmod
    a = _grind(ref_id="r1", audio_path=tmp_path / "a.wav")
    b = _grind(SET, ref_id="r2", audio_path=tmp_path / "b.wav")

    view = botmod.MyGrindsView(store.recent_for_user(7))
    values = [o.value for o in view.children[0].options]

    assert sorted(values) == sorted([str(a), str(b)])


def test_no_picker_at_all_when_there_is_nothing_to_pick():
    """Discord REFUSES a dropdown with zero options - attaching one to an empty /mygrinds would
    make the command fail outright for every brand-new person who runs it."""
    import bot as botmod
    assert botmod.MyGrindsView([]).children == []


def test_choosing_a_grind_hands_the_file_back_privately(tmp_path, monkeypatch):
    import bot as botmod
    wav = tmp_path / "there.wav"
    wav.write_bytes(b"RIFFstill-here")
    n = _grind(ref_id="r1", audio_path=wav)
    monkeypatch.setattr(botmod.bot, "api", FakeEngine(), raising=False)
    monkeypatch.setattr(botmod, "_attachment_for", lambda w, number: _stub_attach(w))

    view = botmod.MyGrindsView(store.recent_for_user(7))
    i, sent = _interaction(user_id=7)
    asyncio.run(view.hand_back(i, n))

    got = sent["followups"][-1]
    assert got["file"] is not None, "the mix was not sent back"
    assert got["ephemeral"] is True, "somebody else's private mix was posted where others can see"


def test_it_will_not_hand_over_somebody_elses_grind(tmp_path, monkeypatch):
    import bot as botmod
    wav = tmp_path / "there.wav"
    wav.write_bytes(b"RIFFstill-here")
    n = _grind(ref_id="r1", audio_path=wav)
    monkeypatch.setattr(botmod.bot, "api", FakeEngine(), raising=False)
    monkeypatch.setattr(botmod, "_attachment_for", lambda w, number: _stub_attach(w))

    view = botmod.MyGrindsView(store.recent_for_user(7))
    i, sent = _interaction(user_id=999)               # not the owner
    asyncio.run(view.hand_back(i, n))

    assert all(f["file"] is None for f in sent.get("followups", [])), \
        "it handed a private mix to somebody who does not own it"


def test_mygrinds_actually_offers_the_picker(tmp_path):
    """The whole fix is worthless if the command never attaches the view."""
    import bot as botmod
    _grind(ref_id="r1", audio_path=tmp_path / "a.wav")
    i, sent = _interaction(user_id=7)

    asyncio.run(botmod.mygrinds_cmd.callback(i))

    assert sent["ephemeral"] is True
    assert sent["view"] is not None and sent["view"].children, \
        "/mygrinds listed the grinds but gave no way to get one back"


def test_mygrinds_still_works_for_somebody_with_nothing():
    """No rows means no dropdown, and the command must still answer rather than raise."""
    import bot as botmod
    i, sent = _interaction(user_id=4242)

    asyncio.run(botmod.mygrinds_cmd.callback(i))

    assert sent["embed"] is not None
    assert not (sent["view"] and sent["view"].children)


def test_a_gone_mix_gets_the_sentence_and_no_file(tmp_path, monkeypatch):
    import bot as botmod
    n = _grind(ref_id="r-old", audio_path=tmp_path / "gone.wav")
    monkeypatch.setattr(botmod.bot, "api", FakeEngine(has=False), raising=False)
    monkeypatch.setattr(botmod, "_attachment_for", lambda w, number: _stub_attach(w))

    view = botmod.MyGrindsView(store.recent_for_user(7))
    i, sent = _interaction(user_id=7)
    asyncio.run(view.hand_back(i, n))

    got = sent["followups"][-1]
    assert got["file"] is None
    assert "gone" in got["content"].lower()
