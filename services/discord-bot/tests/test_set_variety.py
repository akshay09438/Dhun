"""A person's SETS must not all come out the same.

THE BUG THIS PINS (found 2026-08-15, by reading the code the founder asked about — no test saw it).
`bot.py` called `start_set(..., set_index=0)` with the number HARD-CODED. The engine's rule shuffler
seeds a set's mixing-rule order from (user_id, set_index), and `set_index` is the ONLY thing that
makes a person's consecutive sets differ. Sending 0 every time meant:

  * every multi-song grind that person ever built came out in the identical style order —
    measured on the real shuffler: five sets of 5 in a row, all `simple -> chop -> echo -> chop -> echo`; and
  * 🔁 Again on a multi-song grind returned the BYTE-IDENTICAL FILE. A set's cache id is built from
    its pairs and their rules; same pairs + same rules = same id = a cache hit. The button did nothing.

The web app never had this — `takeNextSetIndex()` in apps/web/src/lib/user.ts advances a per-browser
counter. The bot simply never grew the equivalent.

WHY THE COUNTER IS BOUNDED, which is not obvious and is the trap here. The engine's
`rule_shuffle._resolved_set_base` RECURSES from the index it is handed down to 0, so a big index is
not merely slow — it raises RecursionError and the set fails to build. Measured on the real engine
2026-08-15: 900 fine, 1200 raises. So the counter wraps well below that. Wrapping repeats an ordering
once every SET_INDEX_WRAP sets, which nobody can perceive; an unbounded counter would eventually make
every set fail forever, with no way back for that user.
"""
import asyncio
import os
import types
import wave

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


# --- the counter itself -------------------------------------------------------------------

def test_a_persons_sets_each_get_a_fresh_number():
    """0, 1, 2, … — a new number per set is the whole mechanism that varies the style order."""
    assert [store.next_set_index(7) for _ in range(4)] == [0, 1, 2, 3]


def test_two_people_have_their_own_counters():
    """One person building sets must never advance somebody else's sequence."""
    assert store.next_set_index(1) == 0
    assert store.next_set_index(2) == 0      # a different person still starts at their own 0
    assert store.next_set_index(1) == 1
    assert store.next_set_index(2) == 1


def test_the_counter_survives_a_restart():
    """The in-memory version of this would reset on every restart — and Grinder restarts often
    (six times in one evening on 2026-08-14). Then set #1 after a restart would repeat set #1
    before it, which is the exact bug being fixed."""
    assert [store.next_set_index(9) for _ in range(3)] == [0, 1, 2]
    store.reset_for_tests(store.DB_PATH)     # same file, fresh connection: a restart
    assert store.next_set_index(9) == 3


def test_the_counter_can_never_reach_the_depth_that_breaks_the_engine():
    """The engine recurses from set_index down to 0 and dies past ~1000 (measured: 900 ok, 1200
    raises RecursionError). An unbounded counter would therefore brick set-building permanently for
    anyone who got there. The wrap keeps every number the bot can ever emit comfortably clear."""
    assert store.SET_INDEX_WRAP <= 900, "must stay under the engine's recursion ceiling"
    with store._lock:                        # jump the counter near the wrap without 512 round-trips
        c = store.connect()
        c.execute("INSERT OR REPLACE INTO set_counters (user_id, next_index) VALUES (?,?)",
                  (4, store.SET_INDEX_WRAP - 1))
        c.commit()
    assert store.next_set_index(4) == store.SET_INDEX_WRAP - 1
    assert store.next_set_index(4) == 0, "wraps instead of growing without bound"


def test_wrapping_never_emits_a_number_the_engine_would_choke_on():
    """Belt and braces: whatever the stored value, what comes OUT is always in range."""
    with store._lock:
        c = store.connect()
        c.execute("INSERT OR REPLACE INTO set_counters (user_id, next_index) VALUES (?,?)",
                  (5, 10_000))               # a corrupted / hand-edited row must not escape
        c.commit()
    assert 0 <= store.next_set_index(5) < store.SET_INDEX_WRAP


# --- the call site: what the bot actually SENDS ---------------------------------------------
# The bug lived here and nothing guarded it. test_api_client.py checks the client forwards the
# number it is handed; it never checked what the bot hands over.

def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


class _FakeApi:
    """Records every set the bot asks for, and hands back a ready one."""

    def __init__(self):
        self.set_indexes = []

    async def start_set(self, pairs, user_id, set_index=0, user_name=None):
        self.set_indexes.append(set_index)
        return f"set-{len(self.set_indexes)}"

    async def wait_for_set(self, set_id, on_progress=None):
        return types.SimpleNamespace(status="ready", message=None, members=[], duration=1.0)

    async def fetch_set_audio(self, set_id, dest):
        _wav(dest)
        return str(dest)

    async def start_mix(self, a, b, user_id, generation=0, user_name=None):
        return "mix-1"

    async def wait_for_mix(self, mix_id, on_progress=None):
        return types.SimpleNamespace(status="ready", message=None, rule=1)

    async def fetch_audio(self, mix_id, dest):
        _wav(dest)
        return str(dest)


def _ctx(botmod, pairs):
    user = types.SimpleNamespace(id=4242, name="tester", display_name="tester")
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None)
    ctx = botmod.GrindContext(interaction, pairs)
    ctx.number = store.new_grind(user_id=4242, user_name="tester",
                                 pairs=[[a, b, "Beat", "Vocal"] for a, b in pairs],
                                 created_at="2026-08-15T00:00:00+00:00")
    return ctx


@pytest.fixture()
def botmod(monkeypatch):
    import bot as botmod
    fake = _FakeApi()
    monkeypatch.setattr(botmod.bot, "api", fake)
    botmod._TEST_API = fake
    return botmod


def test_two_separate_grinds_by_one_person_ask_for_two_different_sets(botmod):
    """The founder's report, at the seam where it was actually caused."""
    pairs = [("b1", "v1"), ("b2", "v2"), ("b3", "v3")]
    asyncio.run(_ctx(botmod, pairs)._render())
    asyncio.run(_ctx(botmod, pairs)._render())
    sent = botmod._TEST_API.set_indexes
    assert len(sent) == 2
    assert sent[0] != sent[1], f"both grinds asked the engine for the same set: {sent}"


def test_again_on_a_multi_song_grind_asks_for_a_genuinely_different_set(botmod):
    """🔁 Again re-runs the SAME pairs. With a fixed set_index the rules were identical too, so the
    set id was identical and the engine served the cached file back — the same audio, presented as a
    new take. A fresh number is what makes Again mean something."""
    ctx = _ctx(botmod, [("b1", "v1"), ("b2", "v2")])
    asyncio.run(ctx._render())
    asyncio.run(ctx._render())               # what the Again button does
    sent = botmod._TEST_API.set_indexes
    assert sent[0] != sent[1], f"Again re-requested the identical set: {sent}"


def test_a_one_pair_grind_does_not_burn_a_set_number(botmod):
    """A single mix goes through the mix route, which varies by `generation`, not by set_index.
    Consuming a set number there would skip numbers for no reason."""
    asyncio.run(_ctx(botmod, [("b1", "v1")])._render())
    assert botmod._TEST_API.set_indexes == []
    assert store.next_set_index(4242) == 0, "a single mix must not have advanced the set counter"


def test_the_number_sent_is_the_one_the_store_handed_out(botmod):
    """No silent re-mapping between the counter and the engine."""
    asyncio.run(_ctx(botmod, [("b1", "v1"), ("b2", "v2")])._render())
    assert botmod._TEST_API.set_indexes == [0]
    assert store.next_set_index(4242) == 1, "the set consumed exactly one number"
