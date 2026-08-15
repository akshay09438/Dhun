"""One line in the grind room saying the place is alive.

WHY IT EXISTS. Grinds went private on 2026-08-15, which was the founder's call and solved the
overwhelm - but it left `#get-shit-done` with nothing in it at all, and the door design's own words
are that an empty room is the worst thing that can happen to a new community. Founder: "yes, at this
thing where three people are grinding right now, two people are grinding right now".

THE BUG THIS MUST NOT REPEAT, and it is written down in booth.py because it already happened. There
used to be a "⚫ Nobody is listening right now" card meant to be ONE message edited in place - but
the handle to it lived only in memory, so every restart lost it and posted a fresh one, and the
channel filled with a column of identical grey cards. It was deleted rather than fixed. So this
board keeps its message id IN THE DATABASE: a restart finds the same message and edits it.

AND IT MUST NEVER NAG. The same card was also judged "nagging, not information" for announcing an
empty room. When nobody is mid-grind this says what the room has MADE today instead - which is the
social proof that private grinds took away, without putting anyone's music back on the wall.
"""
import asyncio
import os
import types
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import board  # noqa: E402
import store  # noqa: E402

CHANNEL_ID = 4242


def _now_iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class _Msg:
    def __init__(self, mid=77):
        self.id = mid
        self.edits = 0
        self.embed = None
        self.deleted = False

    async def edit(self, **k):
        if self.deleted:
            raise RuntimeError("editing a message that is gone")
        self.edits += 1
        self.embed = k.get("embed")


class _Channel:
    """A channel that can hand back a message by id, like Discord's fetch_message."""

    def __init__(self, existing: _Msg | None = None):
        self.id = CHANNEL_ID
        self.posted: list[_Msg] = []
        self._existing = existing

    async def send(self, **k):
        m = _Msg(mid=100 + len(self.posted))
        m.embed = k.get("embed")
        self.posted.append(m)
        return m

    async def fetch_message(self, mid):
        if self._existing is not None and self._existing.id == mid and not self._existing.deleted:
            return self._existing
        raise LookupError("no such message")


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    board.reset_for_tests()
    yield
    store.reset_for_tests()


def _text(embed) -> str:
    bits = [embed.title or "", embed.description or ""]
    bits += [f"{f.name} {f.value}" for f in getattr(embed, "fields", [])]
    return " ".join(bits).lower()


# --- what it says --------------------------------------------------------------------------

def test_it_says_how_many_are_grinding_right_now():
    ch = _Channel()
    board.started(1)
    board.started(2)
    asyncio.run(board.refresh(ch))
    assert ch.posted, "no board was posted"
    assert "2" in _text(ch.posted[0].embed), f"the count is missing: {_text(ch.posted[0].embed)}"


def test_a_finished_grind_stops_counting_towards_right_now():
    ch = _Channel()
    board.started(1)
    board.started(2)
    board.finished(1)
    assert board.live_count() == 1


def test_it_never_announces_an_empty_room():
    """The card that said "Nobody is listening right now" was deleted for exactly this - an empty
    room is the normal state and a sign about it is nagging."""
    ch = _Channel()
    for _ in range(3):
        store.new_grind(user_id=1, user_name="t", pairs=[["b", "v", "B", "V"]],
                        created_at=_now_iso())
    asyncio.run(board.refresh(ch))
    said = _text(ch.posted[0].embed)
    assert "nobody" not in said and "no one" not in said, f"it nags about an empty room: {said}"
    assert "3" in said, f"with nobody mid-grind it should show what the room has made: {said}"


def test_it_never_judges_a_mix():
    """The standing rule: Grinder never rates, scores or predicts a mix, anywhere, in any wording -
    it would prejudice the reaction data, which is the real product signal."""
    ch = _Channel()
    store.new_grind(user_id=1, user_name="t", pairs=[["b", "v", "B", "V"]], created_at=_now_iso())
    asyncio.run(board.refresh(ch))
    said = _text(ch.posted[0].embed)
    for word in ("best", "great", "good", "bad", "clean", "rough", "fire", "quality", "score"):
        assert word not in said, f"the board is judging mixes: found {word!r} in {said!r}"


def test_yesterdays_grinds_are_not_counted_as_today():
    ch = _Channel()
    store.new_grind(user_id=1, user_name="t", pairs=[["b", "v", "B", "V"]],
                    created_at=_now_iso(minutes_ago=60 * 40))       # ~1.7 days ago
    asyncio.run(board.refresh(ch))
    assert "0" in _text(ch.posted[0].embed) or "nothing" in _text(ch.posted[0].embed)


# --- THE BUG THAT KILLED THE LAST ONE ---------------------------------------------------------

def test_a_restart_edits_the_same_board_instead_of_posting_a_second():
    """THE recorded failure. The old card's handle lived in memory only, so every restart posted a
    fresh one and the channel collected identical cards. The id lives in the database now."""
    ch = _Channel()
    asyncio.run(board.refresh(ch))
    assert len(ch.posted) == 1
    first = ch.posted[0]

    board.reset_for_tests()                      # a RESTART: memory is gone, the database is not
    ch2 = _Channel(existing=first)
    asyncio.run(board.refresh(ch2))

    assert ch2.posted == [], "a restart posted a SECOND board - the old bug is back"
    assert first.edits >= 1, "the restart did not update the board it already had"


def test_a_board_somebody_deleted_is_replaced_rather_than_edited_into_the_void():
    ch = _Channel()
    asyncio.run(board.refresh(ch))
    gone = ch.posted[0]
    gone.deleted = True

    board.reset_for_tests()
    ch2 = _Channel(existing=gone)                # fetch will fail: it is gone
    asyncio.run(board.refresh(ch2))
    assert len(ch2.posted) == 1, "it did not recover from a deleted board"
    assert store.board_message(CHANNEL_ID) == ch2.posted[0].id, "it forgot the replacement"


def test_the_board_is_actually_WIRED_to_grinding(monkeypatch):
    """A board nothing calls is a board that never moves.

    This project has shipped "code exists but never executes" more than once - `_EFFECT_POOL_ENABLED`
    and `USE_AI_ARRANGEMENT` are both sitting in the tree switched off. So this drives a real grind
    and checks the counter went up and then down again."""
    import wave

    import bot as botmod

    seen = []
    monkeypatch.setattr(botmod.board, "started", lambda uid: seen.append(("start", uid)))
    monkeypatch.setattr(botmod.board, "finished", lambda uid: seen.append(("finish", uid)))

    async def _noop_refresh(channel):
        return None
    monkeypatch.setattr(botmod.board, "refresh", _noop_refresh)

    def _wav(path):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 8000)

    class _Api:
        async def start_mix(self, a, b, user_id, generation=0, user_name=None):
            return "m1"

        async def wait_for_mix(self, mix_id, on_progress=None):
            return types.SimpleNamespace(status="ready", message=None, rule=1)

        async def fetch_audio(self, mix_id, dest):
            _wav(dest)
            return str(dest)

    monkeypatch.setattr(botmod.bot, "api", _Api())
    user = types.SimpleNamespace(id=5, name="t", display_name="t")
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None)
    ctx = botmod.GrindContext(interaction, [("b", "v")])
    ctx.number = store.new_grind(user_id=5, user_name="t", pairs=[["b", "v", "B", "V"]],
                                 created_at=_now_iso())
    asyncio.run(ctx._render())

    assert ("start", 5) in seen, "nothing told the board a grind had begun"
    assert ("finish", 5) in seen, "nothing told the board the grind had ended"


def test_a_cold_channel_cache_does_not_lose_the_board():
    """OBSERVED LIVE, 2026-08-15 20:29: `get_channel` returned None at startup and the board simply
    never appeared; the next restart it worked. The cache is filled from gateway events and is not
    guaranteed to be ready at `on_ready`, so a startup board must not depend on that race."""
    ch = _Channel()

    class _ColdCache:
        def get_channel(self, cid):
            return None                      # exactly what happened on that restart

        async def fetch_channel(self, cid):
            return ch

    got = asyncio.run(board.channel_for(_ColdCache(), CHANNEL_ID))
    assert got is ch, "a cold cache still loses the board"


def test_an_unreachable_channel_is_reported_rather_than_swallowed():
    class _Gone:
        def get_channel(self, cid):
            return None

        async def fetch_channel(self, cid):
            raise RuntimeError("no such channel")

    assert asyncio.run(board.channel_for(_Gone(), CHANNEL_ID)) is None


def test_it_does_not_spam_edits():
    """A start and a finish seconds apart must not cost two edits against Discord's budget."""
    ch = _Channel()
    asyncio.run(board.refresh(ch))
    msg = ch.posted[0]
    before = msg.edits
    for _ in range(5):
        asyncio.run(board.refresh(ch))
    assert msg.edits - before <= 1, f"it edited {msg.edits - before} times in a burst"
