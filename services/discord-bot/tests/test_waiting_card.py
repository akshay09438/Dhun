"""The card has to MOVE while a grind is being made.

The problem, from the consumer's seat: someone presses Grind it and then stares at a card that
says "grinding..." and does not change for 25-30 seconds - longer if there is a line. A first
timer reads a motionless card as a broken bot and leaves, which costs more people than any real
failure does. These pin what the card says, and that it does not spend Discord's rate-limit
budget repeating itself.
"""
import asyncio
import os
import types

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import ui  # noqa: E402


# --- what the line says -----------------------------------------------------------------

def test_a_grind_in_the_line_is_told_where_it_is_and_roughly_how_long():
    line = ui.waiting_line(position=6, eta_secs=180)
    assert "6" in line
    assert "3 min" in line


def test_a_short_wait_is_not_dressed_up_as_a_number_of_minutes():
    assert "under a minute" in ui.waiting_line(position=2, eta_secs=25)


def test_a_position_with_no_estimate_still_says_where_you_are():
    """The estimate is the optional part. Never withhold the place in line because the clock
    is unknown - the place is the bit that stops someone thinking it is broken."""
    line = ui.waiting_line(position=4, eta_secs=None)
    assert "4" in line


def test_a_grind_that_is_actually_rendering_says_what_it_is_doing():
    assert "mixing it down" in ui.waiting_line(stage="mixing it down")


def test_the_place_in_line_beats_the_stage_when_both_are_known():
    """While you are waiting, "3 ahead of you" is the useful fact; what the engine is doing for
    somebody else's grind is not."""
    line = ui.waiting_line(stage="mixing it down", position=3, eta_secs=90)
    assert "3" in line and "mixing it down" not in line


def test_an_engine_that_says_nothing_still_reads_as_working():
    """An older engine sends none of these fields. The card must degrade to the old wording,
    never to a blank line that looks like a bug."""
    assert ui.waiting_line() == "grinding..."


def test_the_estimate_is_never_a_false_precision():
    """'about 3 min' is honest about being a guess; '2m41s' reads as a promise the queue
    cannot keep."""
    assert ui._about_how_long(161) == "about 3 min"
    assert ui._about_how_long(0) == ""
    assert ui._about_how_long(None) == ""


def test_the_card_carries_the_live_line(monkeypatch):
    e = ui.submit_embed(user=None, beat="Father Ocean", vocals="Der Lagi",
                        position=6, eta_secs=180)
    assert "6" in e.description
    assert "Father Ocean" in e.description and "Der Lagi" in e.description


# --- and does not spam Discord ----------------------------------------------------------

class _FakeMessage:
    def __init__(self):
        self.edits = 0

    async def edit(self, **_kw):
        self.edits += 1


def _context_with(message):
    """A GrindContext is heavy to build for real, so this exercises the progress handler with
    only the state it actually touches."""
    import bot as botmod
    ctx = object.__new__(botmod.GrindContext)
    ctx.message = message
    ctx._last_line = None
    ctx.interaction = types.SimpleNamespace(user=None)
    ctx.pairs = [("b", "v")]
    ctx.named_pairs = lambda: [("Beat", "Vocal")]
    return ctx


def test_the_card_is_only_edited_when_the_line_actually_changes():
    """Discord rate-limits edits. Re-sending an identical embed every two seconds would spend
    that budget saying nothing, and could throttle the edit that DOES matter - the finished grind."""
    msg = _FakeMessage()
    ctx = _context_with(msg)
    same = types.SimpleNamespace(stage="mixing it down", queue_position=None, queue_eta_secs=None)

    asyncio.run(ctx._on_progress(0.0, same))
    asyncio.run(ctx._on_progress(2.0, same))
    asyncio.run(ctx._on_progress(4.0, same))
    assert msg.edits == 1, f"edited {msg.edits} times for one unchanged stage"

    moved = types.SimpleNamespace(stage="checking it sounds right", queue_position=None,
                                  queue_eta_secs=None)
    asyncio.run(ctx._on_progress(6.0, moved))
    assert msg.edits == 2, "the card did not move when the engine did"


def test_a_card_that_will_not_update_never_fails_the_grind():
    """The audio is the product; the card is a courtesy. A Discord hiccup must not lose a mix
    that was made perfectly well."""
    import discord

    class _Broken(_FakeMessage):
        async def edit(self, **_kw):
            raise discord.HTTPException(types.SimpleNamespace(status=500, reason="x"), "nope")

    ctx = _context_with(_Broken())
    res = types.SimpleNamespace(stage="mixing it down", queue_position=None, queue_eta_secs=None)
    asyncio.run(ctx._on_progress(0.0, res))     # must not raise


def test_no_card_at_all_is_handled(monkeypatch):
    ctx = _context_with(None)
    res = types.SimpleNamespace(stage="grinding", queue_position=None, queue_eta_secs=None)
    asyncio.run(ctx._on_progress(0.0, res))     # must not raise
