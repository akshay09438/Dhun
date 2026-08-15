"""A finished mix must never be left with nothing pointing at it.

WHAT HAPPENED TO AASHWIN, 2026-08-15, measured to the second. He asked for Wake Me Up x Woman at
20:27:41. The bot polled the engine 32 times, every two seconds. At 20:28:45 the bot was shut down -
it logged back in at 20:29:11 - and the engine, which does not care what the bot is doing, finished
that mix at 20:28:49. FOUR SECONDS after the bot died.

The mix was built perfectly and nobody was left holding the receipt. Grind #34 is the only row out
of 39 with no `ref_id` at all, and the only way it was ever found again was hand-matching file
timestamps on disk the next morning.

WHY. `_render` learned the engine's id from `start_mix` and then held it in a local variable for the
whole 50-70 second render, writing it to the row only after the audio had been downloaded. Anything
that killed the process inside that window - a restart while shipping fixes, a crash, the machine
sleeping - orphaned a finished render permanently. The founder restarted six times that evening.

THE TRAP THIS FIX HAD TO AVOID. `ref_id` was doing double duty as "this grind finished": the seeding
count in `_already_ground` treats a row with a ref_id as a completed grind of that pair. Writing the
reference at the start would make the in-flight grind count itself and push that person one position
too far - the exact bug the tests caught during yesterday's build. So the count now excludes the
grind being rendered, by number, rather than relying on the reference being absent.
"""
import asyncio
import os
import types
import wave

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import store  # noqa: E402

PAIR = ("beat-wake-me-up", "vocal-woman")
OTHER = ("beat-rapture", "vocal-gods-plan")


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


class _ApiThatWatchesTheRow:
    """Reads the grind row at the moment the engine would still be working - which is exactly when
    Aashwin's bot was killed."""

    def __init__(self):
        self.number = None
        self.ref_while_rendering = "<never looked>"
        self.ref_id = None

    def _peek(self):
        row = store.get(self.number)
        self.ref_while_rendering = row["ref_id"] if row is not None else None

    async def start_mix(self, a, b, user_id, generation=0, user_name=None):
        self.ref_id = "mix-abc"
        return self.ref_id

    async def wait_for_mix(self, mix_id, on_progress=None):
        self._peek()
        return types.SimpleNamespace(status="ready", message=None, rule=1)

    async def fetch_audio(self, mix_id, dest):
        _wav(dest)
        return str(dest)

    async def start_set(self, pairs, user_id, set_index=0, user_name=None):
        self.ref_id = "set-abc"
        return self.ref_id

    async def wait_for_set(self, set_id, on_progress=None):
        self._peek()
        return types.SimpleNamespace(status="ready", message=None, members=[], duration=1.0)

    async def fetch_set_audio(self, set_id, dest):
        _wav(dest)
        return str(dest)


@pytest.fixture()
def botmod(monkeypatch):
    import bot as botmod
    api = _ApiThatWatchesTheRow()
    monkeypatch.setattr(botmod.bot, "api", api)
    botmod._TEST_API = api
    return botmod


def _ctx(botmod, pairs, user_id=4242):
    user = types.SimpleNamespace(id=user_id, name="tester", display_name="tester")
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None)
    ctx = botmod.GrindContext(interaction, pairs)
    ctx.number = store.new_grind(user_id=user_id, user_name="tester",
                                 pairs=[[a, b, "Beat", "Vocal"] for a, b in pairs],
                                 created_at="2026-08-15T20:27:41+00:00")
    botmod._TEST_API.number = ctx.number
    return ctx


# --- the window itself --------------------------------------------------------------------------

def test_the_reference_is_written_while_the_engine_is_still_rendering(botmod):
    """THE AASHWIN CASE. If the process dies here, the row must already know where the mix is."""
    asyncio.run(_ctx(botmod, [PAIR])._render())

    assert botmod._TEST_API.ref_while_rendering == "mix-abc", (
        "the row still had no reference while the engine was working, so a restart at that moment "
        "orphans the finished mix exactly as it did on 2026-08-15")


def test_a_set_records_its_reference_early_too(botmod):
    """A set takes LONGER than a single mix, so its orphan window is the wider one."""
    asyncio.run(_ctx(botmod, [PAIR, OTHER])._render())

    assert botmod._TEST_API.ref_while_rendering == "set-abc"


def test_the_reference_is_still_right_when_it_finishes(botmod):
    """Writing early must not leave a stale or missing value behind at the end."""
    ctx = _ctx(botmod, [PAIR])
    asyncio.run(ctx._render())

    assert store.get(ctx.number)["ref_id"] == "mix-abc"


# --- and the trap it must not spring --------------------------------------------------------------

def test_a_grind_in_flight_does_not_push_that_person_along(botmod):
    """THE REGRESSION GUARD. `_already_ground` counts a row with a reference as a FINISHED grind of
    that pair. Now that the reference is written at the start, the grind being rendered right now
    would count itself and start everyone one position too far - handing them a take they have not
    had, and skipping one they have not heard."""
    ctx = _ctx(botmod, [PAIR], user_id=77)
    store.set_pairs(ctx.number, [[PAIR[0], PAIR[1], "Beat", "Vocal"]], ref_id="mix-abc")

    assert store.next_grind_position(77, *PAIR, exclude=ctx.number) == 0, (
        "the in-flight grind counted itself")


def test_finished_grinds_of_the_same_pair_are_still_counted(botmod):
    """The exclusion must be surgical - only the one grind being rendered, never the history."""
    for _ in range(2):
        n = store.new_grind(user_id=88, user_name="t",
                            pairs=[[PAIR[0], PAIR[1], "Beat", "Vocal"]],
                            created_at="2026-08-15T13:00:00+00:00")
        store.set_pairs(n, [[PAIR[0], PAIR[1], "Beat", "Vocal"]], ref_id=f"mix-{n}")
    live = store.new_grind(user_id=88, user_name="t",
                           pairs=[[PAIR[0], PAIR[1], "Beat", "Vocal"]],
                           created_at="2026-08-15T20:00:00+00:00")
    store.set_pairs(live, [[PAIR[0], PAIR[1], "Beat", "Vocal"]], ref_id="mix-live")

    assert store.next_grind_position(88, *PAIR, exclude=live) == 2


def test_two_fresh_grinds_of_a_pair_still_get_different_mixes(botmod):
    """Yesterday's fix must survive this one: grinds #28/#29/#30 were the same file three times."""
    a = _ctx(botmod, [PAIR], user_id=5)
    asyncio.run(a._render())
    b = _ctx(botmod, [PAIR], user_id=5)
    asyncio.run(b._render())

    got = [store.get(a.number)["ref_id"], store.get(b.number)["ref_id"]]
    assert all(got), "a grind finished without recording where its mix is"
