"""The buttons on a grind must still work after Grinder restarts.

WHAT THE FOUNDER SAW, 2026-08-15. Their card for GRIND #35 (Rapture x God's Plan, posted 20:35)
showed "⚠ Grinder didn't respond in time" when they pressed a button. Measured: the bot restarted at
21:01 and there had been no grind since, so the only cards in existence were older than the restart.

WHY. `GrindView` was built with `timeout=1800` and was never registered as a persistent view, so it
existed only in the memory of the process that posted it. After a restart Discord delivers the button
press to a bot that has no handler for it, nothing answers, and Discord shows "didn't respond in
time". The handoff has recorded this since 2026-08-14 ("a /grind card is NOT a persistent view - any
restart kills every open card"); it stayed harmless only while nobody restarted mid-session. Six
restarts in one evening made it the founder's whole experience of the bot.

`door.DoorView` and `door.ReviewView` already solve exactly this - they are re-registered in
`setup_hook` because a lobby button sits in a channel for weeks. A grind card is no different.

THE PART THAT NEEDS CARE: a re-registered view is a FRESH object with no memory of which grind it
belongs to. It rebuilds that from the database, keyed on the message the button is attached to - and
it takes the OWNER from that row, never from whoever pressed, so a restart cannot quietly hand
somebody else's grind to the wrong person.
"""
import asyncio
import json
import os
import types

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import store  # noqa: E402

PAIRS = [["beat-1", "vocal-1", "Beat One", "Vocal One"]]


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


def _interaction(user_id=1, message_id=555):
    sent = {}

    class _Resp:
        def __init__(self):
            self._done = False

        def is_done(self):
            return self._done

        async def defer(self, **k):
            self._done = True
            sent["deferred"] = True

        async def send_message(self, *a, **k):
            self._done = True
            sent["msg"] = a[0] if a else k.get("content")

    class _Follow:
        async def send(self, *a, **k):
            sent.setdefault("followups", []).append(a[0] if a else k.get("content"))

    i = types.SimpleNamespace(
        user=types.SimpleNamespace(id=user_id, name="t", display_name="t"),
        message=types.SimpleNamespace(id=message_id),
        response=_Resp(), followup=_Follow(), guild=None, channel=None)
    return i, sent


def _stored_grind(user_id=1, message_id=555):
    n = store.new_grind(user_id=user_id, user_name="tester", pairs=PAIRS,
                        created_at="2026-08-15T20:35:55+00:00")
    store.attach_message(n, message_id)
    return n


# --- it must be persistent at all ------------------------------------------------------------

def test_the_card_is_a_persistent_view():
    """A view with a timeout dies with the process that made it. The door already learned this."""
    import bot as botmod
    v = botmod.GrindView(None)
    assert v.timeout is None, (
        "GrindView still has a timeout, so its buttons die on restart and Discord shows "
        "'didn't respond in time'")


def test_it_is_re_registered_when_the_bot_starts():
    """Persistent is not enough - the bot has to hand it back to discord.py on every start, the
    same way DoorView and ReviewView are."""
    import inspect

    import bot as botmod
    src = inspect.getsource(botmod.PromptDJBot.setup_hook)
    assert "GrindView" in src, (
        "setup_hook does not re-register GrindView, so a restarted bot has no handler for the "
        "buttons on cards that are already posted")


def test_every_button_has_a_stable_id():
    """discord.py routes a press to a persistent view by custom_id. A button without one cannot be
    matched after a restart."""
    import bot as botmod
    ids = [getattr(c, "custom_id", None) for c in botmod.GrindView(None).children]
    assert all(ids), f"a button has no custom_id: {ids}"


# --- and it must know which grind it belongs to ------------------------------------------------

def test_a_forgotten_card_finds_its_grind_again_from_the_database():
    import bot as botmod
    n = _stored_grind(user_id=7, message_id=999)
    view = botmod.GrindView(None)            # what exists after a restart
    i, _ = _interaction(user_id=7, message_id=999)
    ctx = asyncio.run(view._context(i))
    assert ctx is not None, "the card could not work out which grind it was"
    assert ctx.number == n
    assert ctx.pairs == [("beat-1", "vocal-1")]


def test_the_owner_comes_from_the_GRIND_not_from_whoever_pressed():
    """Otherwise a restart would silently transfer somebody's grind to the next person to press."""
    import bot as botmod
    _stored_grind(user_id=7, message_id=999)
    view = botmod.GrindView(None)
    i, _ = _interaction(user_id=4242, message_id=999)     # a DIFFERENT person pressing
    ctx = asyncio.run(view._context(i))
    assert ctx.owner_id == 7, "the presser was treated as the owner"


def test_a_card_with_no_grind_behind_it_says_so_instead_of_going_quiet():
    """A message the database has never heard of (an old build, a wiped database) must get an
    answer - silence is what 'didn't respond in time' looks like to a person."""
    import bot as botmod
    view = botmod.GrindView(None)
    i, sent = _interaction(message_id=123456)
    asyncio.run(view.again.callback(i))     # discord.py binds the view; the press passes only the interaction
    said = " ".join(str(x) for x in ([sent.get("msg")] + sent.get("followups", [])) if x)
    assert said.strip(), "the button did nothing at all - exactly the reported symptom"


def test_a_live_card_still_uses_the_context_it_already_has():
    """The normal path must not start doing database lookups it does not need."""
    import bot as botmod
    marker = object()
    view = botmod.GrindView(marker)
    i, _ = _interaction()
    assert asyncio.run(view._context(i)) is marker
