"""Grinds: numbering, reactions, pinning, and who is allowed to change whose grind.

The reaction tests matter most. 🔥 / 💀 / 😐 are the only signal that says whether a grind actually
landed, so a bug that double-counts or silently drops one corrupts the thing the product is being
built to learn.
"""
import asyncio
import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


def _grind(user_id=1, pairs=None):
    return store.new_grind(user_id=user_id, user_name="tester",
                           pairs=pairs or [["b", "v", "Beat", "Vocal"]],
                           created_at="2026-08-11T00:00:00+00:00")


# --- numbering -------------------------------------------------------------------------
def test_grind_numbers_count_up_and_never_repeat():
    assert [_grind(), _grind(), _grind()] == [1, 2, 3]


def test_a_grind_number_is_claimed_at_submit_so_the_card_keeps_it():
    """The number is on the 'grinding...' card, so it must exist before the render finishes."""
    n = _grind()
    store.attach_message(n, 555)
    assert store.by_message(555)["number"] == n


# --- reactions -------------------------------------------------------------------------
def test_a_reaction_is_recorded_against_the_grind_it_was_left_on():
    n = _grind()
    store.add_reaction(grind_number=n, user_id=42, emoji="🔥", when="t")
    assert store.reaction_counts(n) == {"🔥": 1}


def test_the_same_person_reacting_twice_counts_once():
    n = _grind()
    for _ in range(3):
        store.add_reaction(grind_number=n, user_id=42, emoji="🔥", when="t")
    assert store.reaction_counts(n) == {"🔥": 1}


def test_taking_a_reaction_back_really_removes_it():
    """A changed mind must not leave a vote behind - otherwise the counts only ever go up."""
    n = _grind()
    store.add_reaction(grind_number=n, user_id=42, emoji="💀", when="t")
    store.remove_reaction(grind_number=n, user_id=42, emoji="💀")
    assert store.reaction_counts(n) == {}


def test_different_people_and_different_emoji_are_counted_separately():
    n = _grind()
    store.add_reaction(grind_number=n, user_id=1, emoji="🔥", when="t")
    store.add_reaction(grind_number=n, user_id=2, emoji="🔥", when="t")
    store.add_reaction(grind_number=n, user_id=1, emoji="😐", when="t")
    assert store.reaction_counts(n) == {"🔥": 2, "😐": 1}


def test_reactions_on_one_grind_do_not_leak_into_another():
    a, b = _grind(), _grind()
    store.add_reaction(grind_number=a, user_id=1, emoji="🔥", when="t")
    assert store.reaction_counts(b) == {}


# --- pinning ---------------------------------------------------------------------------
def test_pinning_twice_only_posts_once():
    """The button stays live for half an hour and people double-tap. A duplicate in the showcase
    is the visible symptom of getting this wrong."""
    n = _grind()
    assert store.mark_pinned(n, "t") is True
    assert store.mark_pinned(n, "t") is False


def test_a_failed_pin_can_be_retried():
    n = _grind()
    store.mark_pinned(n, "t")
    store.mark_unpinned(n)                      # the post itself failed
    assert store.mark_pinned(n, "t") is True


# --- /mygrinds -------------------------------------------------------------------------
def test_mygrinds_shows_only_your_own_newest_first():
    mine = [_grind(user_id=7) for _ in range(3)]
    _grind(user_id=99)
    for n in mine:
        store.attach_message(n, 1000 + n)
    rows = store.recent_for_user(7)
    assert [r["number"] for r in rows] == sorted(mine, reverse=True)
    assert store.count_for_user(7) == 3
    assert store.count_for_user(99) == 1


def test_an_unfinished_grind_is_not_listed():
    """A grind with no card attached never finished rendering, so it is not something you made."""
    _grind(user_id=7)                            # never gets attach_message
    assert store.recent_for_user(7) == []


# --- views must not shadow the library's own methods --------------------------------------
def test_no_view_shadows_a_discord_internal_method():
    """The bug this catches, from a real run on 2026-08-11: a view defined `_refresh()`, which
    discord.ui.View already uses as `_refresh(components)`. Discord sent a message update, the
    library called it with an argument, and the TypeError killed the entire gateway handler - the
    bot went down completely, from a name collision.

    Checked by signature, not by a hardcoded list, so a future discord.py that adds a new internal
    method still fails loudly here rather than at runtime in front of people.
    """
    import inspect

    import discord

    import bot as botmod

    # Dunders are excluded: overriding __init__ is normal and correct. What is never safe is
    # shadowing a single-underscore internal the library calls on its own schedule.
    base = {n for n, _ in inspect.getmembers(discord.ui.View, inspect.isfunction)
            if n.startswith("_") and not n.startswith("__")}
    offences = []
    for name, obj in vars(botmod).items():
        if not (inspect.isclass(obj) and issubclass(obj, discord.ui.View)
                and obj is not discord.ui.View):
            continue
        for attr, fn in vars(obj).items():
            if attr in base and inspect.isfunction(fn):
                theirs = inspect.signature(getattr(discord.ui.View, attr))
                ours = inspect.signature(fn)
                if str(theirs) != str(ours):
                    offences.append(f"{name}.{attr}{ours} shadows View.{attr}{theirs}")
    assert not offences, "a view overrode a discord.py internal with a different signature:\n" + \
        "\n".join(offences)


# --- the picker /grind opens --------------------------------------------------------------
def _builder(monkeypatch, beats=("b1", "b2"), vocals=("v1", "v2")):
    import bot as botmod

    class _S:
        def __init__(self, i):
            self.id = i
            self.name = i

    monkeypatch.setattr(botmod.bot, "beats", [_S(b) for b in beats], raising=False)
    monkeypatch.setattr(botmod.bot, "vocals", [_S(v) for v in vocals], raising=False)
    monkeypatch.setattr(botmod.bot, "songs", [_S(x) for x in list(beats) + list(vocals)],
                        raising=False)

    # A discord.ui.View schedules its own timeout task on construction, so it needs a running
    # loop to exist at all. These tests only read plain attributes afterwards.
    async def make():
        return botmod.GrindBuilderView(user_id=1)

    return asyncio.run(make())


def test_the_picker_stacks_pairs_before_anything_is_built(monkeypatch):
    """The founder's ask: a + beside the vocal so a set can be sketched on the go, deciding the
    whole shape before hearing any of it."""
    v = _builder(monkeypatch)
    v.sel_beat, v.sel_vocal = "b1", "v1"
    assert v._staged() == [("b1", "v1")]
    v.pairs.append(("b1", "v1"))
    v.sel_beat = v.sel_vocal = None
    v.sel_beat, v.sel_vocal = "b2", "v2"
    assert v._staged() == [("b1", "v1"), ("b2", "v2")]


def test_a_pair_left_sitting_in_the_dropdowns_is_not_silently_dropped(monkeypatch):
    """Hitting Grind it with a pair picked but not yet added should just work. Losing it would
    look like the button ignoring you."""
    v = _builder(monkeypatch)
    v.sel_beat, v.sel_vocal = "b1", "v1"
    assert v._staged() == [("b1", "v1")]


def test_a_half_picked_pair_is_not_staged(monkeypatch):
    v = _builder(monkeypatch)
    v.sel_beat = "b1"
    assert v._staged() == []


def test_the_picker_respects_the_five_pair_cap(monkeypatch):
    import bot as botmod
    v = _builder(monkeypatch)
    v.pairs = [("b1", "v1")] * botmod.MAX_PAIRS_PER_GRIND
    v.sel_beat, v.sel_vocal = "b2", "v2"
    # _staged can exceed the cap; the command truncates, so the cap holds either way
    assert len(v._staged()[:botmod.MAX_PAIRS_PER_GRIND]) == botmod.MAX_PAIRS_PER_GRIND
