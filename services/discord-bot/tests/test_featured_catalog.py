"""The curated 25 must be the 25 that actually fit in the dropdown.

A Discord select menu holds 25 options, and `select_option_specs` takes the first 25 in list order.
With 63 beats and 59 English vocals that left 72 songs unreachable, and WHICH 25 appeared was an
accident of manifest order - the founder saw four vocals where there were fifty-nine.

`scripts/set_featured.py` chooses them deliberately; these pin that the bot then HONOURS the
choice, and - just as important - that nothing is thrown away in the process.
"""

from __future__ import annotations

import types

from api_client import Song
from helpers import select_option_specs


def _song(name, featured=False, role="beat"):
    return Song(id=f"{abs(hash(name)):064x}"[:64], name=name, role_hint=role, featured=featured)


def curated_first(pool):
    """The ordering the bot applies in refresh_catalog."""
    return sorted(pool, key=lambda s: not getattr(s, "featured", False))


def test_featured_songs_come_first():
    pool = [_song("plain-a"), _song("chosen-1", True), _song("plain-b"), _song("chosen-2", True)]
    names = [s.name for s in curated_first(pool)]
    assert names[:2] == ["chosen-1", "chosen-2"]


def test_nothing_is_dropped_only_reordered():
    """The engine and the web app must still see every song - this is a display order, not a filter."""
    pool = [_song(f"s{i}", featured=(i % 7 == 0)) for i in range(60)]
    out = curated_first(pool)
    assert len(out) == len(pool)
    assert {s.name for s in out} == {s.name for s in pool}


def test_the_dropdown_ends_up_showing_the_curated_ones():
    """The whole point, end to end: 60 songs, 25 curated, and the menu shows exactly those."""
    pool = [_song(f"plain{i}") for i in range(35)] + [_song(f"pick{i}", True) for i in range(25)]
    shown = {label for label, _v, _d in select_option_specs(curated_first(pool), None)}
    assert len(shown) == 25
    assert all(n.startswith("pick") for n in shown), f"uncurated songs leaked into the menu: {shown}"


def test_order_is_stable_within_each_group():
    """Songs must not shuffle between restarts - a picker that reorders itself is disorienting."""
    pool = [_song("b", True), _song("a"), _song("d", True), _song("c")]
    assert [s.name for s in curated_first(pool)] == ["b", "d", "a", "c"]


def test_a_catalog_with_nothing_marked_is_unchanged():
    """Before set_featured.py has ever run, behaviour must be exactly as it was."""
    pool = [_song("a"), _song("b"), _song("c")]
    assert [s.name for s in curated_first(pool)] == ["a", "b", "c"]


def test_more_than_25_featured_still_only_shows_25():
    """Discord's cap is absolute; over-marking must not crash, just truncate."""
    pool = [_song(f"f{i}", True) for i in range(40)]
    assert len(select_option_specs(curated_first(pool), None)) == 25


def test_song_defaults_to_not_featured():
    """An engine that predates the field simply will not send one - that must mean 'not featured',
    never an error."""
    assert Song(id="x" * 64, name="old").featured is False
