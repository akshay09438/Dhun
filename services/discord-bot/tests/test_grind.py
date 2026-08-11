"""Grinds: numbering, reactions, pinning, and who is allowed to change whose grind.

The reaction tests matter most. 🔥 / 💀 / 😐 are the only signal that says whether a grind actually
landed, so a bug that double-counts or silently drops one corrupts the thing the product is being
built to learn.
"""
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
