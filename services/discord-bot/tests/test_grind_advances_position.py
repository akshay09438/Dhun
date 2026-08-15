"""Grinding the same two songs again must give you a DIFFERENT mix.

THE BUG, CAUGHT IN LIVE USER DATA 2026-08-15. Grinds #28 (a real user), #29 and #30 (the founder)
were all One Dance x Old Town Road and all three carried the IDENTICAL ref_id
cfe221c35b0b38f02caf4379166baa79ca7a71a285faeca64b730137d6b0a7de. The engine BUILT it exactly once -
#29 and #30 wrote no engine event at all, because both were pure cache hits handed the same file.

WHY. `GrindContext.generation` defaults to 0 and ONLY the "Again" button increments it. So every
fresh `/grind` of a pair is position 0 -> the same rule -> the same take -> the same mix id -> the
identical cached audio, for that person, forever. Measured against the real shuffler: the founder's
sequence for this pair is chop -> echo -> simple -> echo -> chop, and a fresh `/grind` always dealt
"chop".

Founder, 2026-08-15: "if I grinded a mix and if I'm grinding the same mix again, I should [get] a
different mix personally... You have put this feature on if I click again, but if I do /grind also,
then it should give me a different mix with the different rule."

WHY A DIFFERENT POSITION IS ENOUGH TO CHANGE THE AUDIO, measured rather than assumed: the position
drives BOTH the rule and the take, and the take really does move the arrangement - takes 1..6 of
this pair place the vocal at six genuinely different sets of anchors before cycling. So advancing
one step changes the style AND where the singing lands, and the mix id with them.

DELIBERATELY NOT FIXED (founder's explicit call): two DIFFERENT people who pick the same pair can
still be handed the same file, because a mix's identity ignores who made it. That stays as it is.
"""
import asyncio
import os
import types
import wave

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import store  # noqa: E402

PAIR = ("beat-one-dance", "vocal-old-town-road")
OTHER = ("beat-anchor-point", "vocal-location")


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


# --- the counter ---------------------------------------------------------------------------

def test_grinding_the_same_pair_again_moves_you_along():
    """0, 1, 2, 3 - the whole point. Each step is a different style AND a different arrangement."""
    got = [store.next_grind_position(7, *PAIR) for _ in range(4)]
    assert got == [0, 1, 2, 3]


def test_each_pair_has_its_own_place():
    """Grinding a different pair must not skip you forward on this one - the rule sequence is per
    (person, pair), so the count has to be too."""
    assert store.next_grind_position(7, *PAIR) == 0
    assert store.next_grind_position(7, *OTHER) == 0
    assert store.next_grind_position(7, *PAIR) == 1
    assert store.next_grind_position(7, *OTHER) == 1


def test_two_people_count_separately():
    """One person grinding must never move somebody else along."""
    assert store.next_grind_position(1, *PAIR) == 0
    assert store.next_grind_position(2, *PAIR) == 0
    assert store.next_grind_position(1, *PAIR) == 1


def test_it_survives_a_restart():
    """In-memory would reset on every restart - and Grinder restarted six times in one evening on
    2026-08-14. Then the first grind after a restart would repeat the first grind before it, which
    is precisely the bug being fixed."""
    assert [store.next_grind_position(9, *PAIR) for _ in range(3)] == [0, 1, 2]
    store.reset_for_tests(store.DB_PATH)          # same file, fresh connection: a restart
    assert store.next_grind_position(9, *PAIR) == 3


def test_the_position_stays_small_enough_to_be_cheap():
    """rule_for_available walks the sequence from 0 to the position, so a huge number is slow even
    where it does not break. Mirrors the set counter's wrap for the same reason."""
    assert store.GRIND_POSITION_WRAP <= 900
    with store._lock:
        c = store.connect()
        c.execute("INSERT OR REPLACE INTO grind_positions (user_id, song1_id, song2_id, next_index) "
                  "VALUES (?,?,?,?)", (4, PAIR[0], PAIR[1], store.GRIND_POSITION_WRAP - 1))
        c.commit()
    assert store.next_grind_position(4, *PAIR) == store.GRIND_POSITION_WRAP - 1
    assert store.next_grind_position(4, *PAIR) == 0, "wraps rather than growing without bound"


def test_it_starts_past_the_grinds_you_have_already_had():
    """THE FIRST GRIND AFTER THIS FIX MUST NOT REPEAT ONE OF THE OLD ONES.

    The counter is new, so it would naturally hand out 0 - the very position that produced the
    identical file three times. The founder's next `/grind` would then show the bug one more time,
    on the test that is meant to prove it fixed. So the first time a pair is asked for, the count
    starts past whatever that person has already ground of that pair."""
    for _ in range(3):                       # the three real grinds of this pair (#28, #29, #30)
        n = store.new_grind(user_id=7, user_name="tester",
                            pairs=[[PAIR[0], PAIR[1], "Beat", "Vocal"]],
                            created_at="2026-08-15T13:00:00+00:00")
        # they FINISHED - a ref_id is what says a grind actually produced a mix, and it is only
        # written after the render, which is what keeps the in-flight grind from counting itself
        store.set_pairs(n, [[PAIR[0], PAIR[1], "Beat", "Vocal"]], ref_id=f"mix-{n}")
    assert store.next_grind_position(7, *PAIR) == 3, "it handed back a position already used"
    assert store.next_grind_position(7, *PAIR) == 4


def test_history_only_counts_that_persons_grinds_of_that_pair():
    """Somebody else's grinds, and this person's grinds of OTHER pairs, must not push them along."""
    store.new_grind(user_id=99, user_name="other", pairs=[[PAIR[0], PAIR[1], "B", "V"]],
                    created_at="2026-08-15T13:00:00+00:00")
    store.new_grind(user_id=7, user_name="tester", pairs=[[OTHER[0], OTHER[1], "B", "V"]],
                    created_at="2026-08-15T13:00:00+00:00")
    assert store.next_grind_position(7, *PAIR) == 0


def test_a_multi_pair_grind_in_the_history_is_not_counted():
    """A set went through the set route and never used a pair position, so it must not skip one."""
    store.new_grind(user_id=7, user_name="tester",
                    pairs=[[PAIR[0], PAIR[1], "B", "V"], [OTHER[0], OTHER[1], "B", "V"]],
                    created_at="2026-08-15T13:00:00+00:00")
    assert store.next_grind_position(7, *PAIR) == 0


def test_a_corrupt_row_can_never_escape_the_range():
    with store._lock:
        c = store.connect()
        c.execute("INSERT OR REPLACE INTO grind_positions (user_id, song1_id, song2_id, next_index) "
                  "VALUES (?,?,?,?)", (5, PAIR[0], PAIR[1], 10_000))
        c.commit()
    assert 0 <= store.next_grind_position(5, *PAIR) < store.GRIND_POSITION_WRAP


# --- the call site, which is where the bug lived ---------------------------------------------

def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


class _FakeApi:
    def __init__(self):
        self.generations = []
        self.set_indexes = []

    async def start_mix(self, a, b, user_id, generation=0, user_name=None):
        self.generations.append(generation)
        return f"mix-{len(self.generations)}"

    async def wait_for_mix(self, mix_id, on_progress=None):
        return types.SimpleNamespace(status="ready", message=None, rule=1)

    async def fetch_audio(self, mix_id, dest):
        _wav(dest)
        return str(dest)

    async def start_set(self, pairs, user_id, set_index=0, user_name=None):
        self.set_indexes.append(set_index)
        return f"set-{len(self.set_indexes)}"

    async def wait_for_set(self, set_id, on_progress=None):
        return types.SimpleNamespace(status="ready", message=None, members=[], duration=1.0)

    async def fetch_set_audio(self, set_id, dest):
        _wav(dest)
        return str(dest)


@pytest.fixture()
def botmod(monkeypatch):
    import bot as botmod
    fake = _FakeApi()
    monkeypatch.setattr(botmod.bot, "api", fake)
    botmod._TEST_API = fake
    return botmod


def _ctx(botmod, pairs, user_id=4242):
    user = types.SimpleNamespace(id=user_id, name="tester", display_name="tester")
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None)
    ctx = botmod.GrindContext(interaction, pairs)
    ctx.number = store.new_grind(user_id=user_id, user_name="tester",
                                 pairs=[[a, b, "Beat", "Vocal"] for a, b in pairs],
                                 created_at="2026-08-15T00:00:00+00:00")
    return ctx


def test_two_fresh_grinds_of_the_same_pair_ask_for_different_mixes(botmod):
    """THE FOUNDER'S REPORT, at the seam where it was caused. Grinds #29 and #30 both sent
    generation 0 and were handed the same file back."""
    asyncio.run(_ctx(botmod, [PAIR])._render())
    asyncio.run(_ctx(botmod, [PAIR])._render())
    sent = botmod._TEST_API.generations
    assert len(sent) == 2
    assert sent[0] != sent[1], f"both grinds asked the engine for the same mix: {sent}"


def test_again_still_moves_you_along_too(botmod):
    """The button that already worked must keep working, and must not land back on something the
    person has just had."""
    ctx = _ctx(botmod, [PAIR])
    asyncio.run(ctx._render())
    asyncio.run(ctx._render())          # what Again does
    asyncio.run(ctx._render())
    sent = botmod._TEST_API.generations
    assert len(set(sent)) == 3, f"Again repeated a take: {sent}"


def test_grinding_a_different_pair_does_not_skip_this_one(botmod):
    """Interleaving pairs must not push this pair's sequence forward."""
    asyncio.run(_ctx(botmod, [PAIR])._render())
    asyncio.run(_ctx(botmod, [OTHER])._render())
    asyncio.run(_ctx(botmod, [PAIR])._render())
    g = botmod._TEST_API.generations
    assert g[0] == 0 and g[1] == 0 and g[2] == 1, f"positions leaked between pairs: {g}"


def test_a_multi_pair_grind_does_not_consume_a_single_pair_position(botmod):
    """Two or more pairs go through the SET route, which varies by set_index, not by generation."""
    asyncio.run(_ctx(botmod, [PAIR, OTHER])._render())
    assert botmod._TEST_API.generations == []
    assert store.next_grind_position(4242, *PAIR) == 0, "a set must not advance a pair's position"


def test_someone_else_grinding_does_not_move_your_place(botmod):
    asyncio.run(_ctx(botmod, [PAIR], user_id=111)._render())
    asyncio.run(_ctx(botmod, [PAIR], user_id=222)._render())
    asyncio.run(_ctx(botmod, [PAIR], user_id=111)._render())
    g = botmod._TEST_API.generations
    assert g == [0, 0, 1], f"one person's grinding moved another's place: {g}"
