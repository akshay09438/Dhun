"""Ten moving cards in one channel must not shout over each other.

Found by tracing the ten-people case on 2026-08-12: each card was already polite ON ITS OWN
(`_on_progress` edits only when the line changes), but Discord rate-limits edits PER CHANNEL and
the cards had no knowledge of each other whatsoever - no shared counter, no coordination.

Being rate-limited does not lose anybody's mix; it makes cards freeze and update late while the
whole channel's edits queue behind each other. Degradation, not failure - but it degrades exactly
when the room is busiest, which is the worst possible time.
"""
from __future__ import annotations

import editbudget


class FakeClock:
    """A hand-wound clock. Real time in a rate-limit test either makes it slow or makes it flaky."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


def test_a_quiet_channel_lets_everything_through():
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=FakeClock())
    assert all(b.allow(1) for _ in range(4))


def test_the_budget_runs_out_and_stops_saying_yes():
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=FakeClock())
    for _ in range(4):
        b.allow(1)
    assert b.allow(1) is False


def test_ten_cards_in_one_channel_share_one_budget():
    """THE ACTUAL CASE. Ten separate grinds, each asking once, all in the same channel. Without a
    shared budget every one of them would have gone out and blown the channel's allowance."""
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=FakeClock())
    allowed = [b.allow(channel_id=999) for _ in range(10)]
    assert sum(allowed) == 4, "the channel's whole allowance, not four per card"


def test_two_channels_do_not_steal_from_each_other():
    """Discord's limit is per channel, so a busy #get-shit-done must not silence a second room."""
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=FakeClock())
    for _ in range(4):
        b.allow(1)
    assert b.allow(1) is False
    assert b.allow(2) is True


def test_the_budget_refills_as_the_window_slides():
    clock = FakeClock()
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=clock)
    for _ in range(4):
        b.allow(1)
    assert b.allow(1) is False
    clock.advance(5.1)
    assert b.allow(1) is True, "a spent budget must recover, not stay spent forever"


def test_it_is_a_sliding_window_not_a_fixed_bucket():
    """Two edits now and two in three seconds must not both count against the same reset."""
    clock = FakeClock()
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=clock)
    b.allow(1); b.allow(1)
    clock.advance(3.0)
    b.allow(1); b.allow(1)
    assert b.allow(1) is False          # all four still inside the 5s window
    clock.advance(2.2)                  # the first two have now aged out
    assert b.allow(1) is True


def test_a_refused_edit_is_not_recorded_as_spent():
    """Otherwise asking repeatedly while refused would keep pushing the recovery further away and
    the channel would never un-stick."""
    clock = FakeClock()
    b = editbudget.EditBudget(edits=4, window_secs=5.0, clock=clock)
    for _ in range(4):
        b.allow(1)
    for _ in range(20):
        b.allow(1)                      # hammered while refused
    assert b.spent_in(1) == 4
    clock.advance(5.1)
    assert b.allow(1) is True


def test_the_default_sits_under_discords_published_limit():
    """Discord allows about 5 edits per 5 seconds per channel. The spare slot is headroom for the
    edits that BYPASS this budget - a finished mix, a failure message - and for anything else
    posting in the channel."""
    assert editbudget.DEFAULT_EDITS < 5
    assert editbudget.DEFAULT_WINDOW_SECS == 5.0
