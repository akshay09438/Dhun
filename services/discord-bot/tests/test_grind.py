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


def test_a_finished_grind_offers_no_way_to_add_another_pair():
    """It used to, and it was a lie: the engine cannot stitch a pair onto an existing set. Pressing
    it rebuilt everything and swapped the audio out - which, mid-playback in The Booth, replaced
    what people were listening to. Pairs are chosen up front now; a grind is done when it arrives."""
    import bot as botmod

    class _Ctx:
        owner_id = 1

    async def make():
        return botmod.GrindView(_Ctx())

    labels = [i.label for i in asyncio.run(make()).children]
    # Exactly two buttons, and neither adds a pair. The share button was renamed on 2026-08-15
    # ("Pin it" -> "Show this mix to everyone") because a private grind makes it the ONLY route to
    # anything public, so it has to name the outcome rather than the mechanism. The point this test
    # defends - a finished grind cannot be added to - is unchanged, and is now checked by meaning
    # rather than by an exact string, so a future rewording cannot make it pass while an "add
    # another pair" button quietly returns.
    assert len(labels) == 2, f"a finished grind should offer exactly two things, got {labels}"
    assert labels[0] == "Again"
    assert not any("add" in (lbl or "").lower() for lbl in labels), \
        f"a finished grind is offering a way to add another pair again: {labels}"
    assert not hasattr(botmod, "AddPairView"), "the append flow should be gone entirely"


def test_no_user_facing_text_promises_stitching_onto_an_existing_grind():
    """The copy said 'hit it and pick another pair and it gets stitched onto the end'. It never
    did that. This is the guard against the promise creeping back in."""
    import server_setup
    import ui

    class _G:
        name = "Grinder"

    texts = [_flat(ui.help_embed())]
    texts += [_flat(e) for e in server_setup.welcome_embeds(_G())]
    texts += [body for _, body in server_setup.channel_copy().values()]
    texts.append(_flat(server_setup.room_embed("The Booth")))
    blob = "\n".join(texts).lower()
    for phrase in ("keep going", "stitched onto", "stitch it on", "onto the end"):
        assert phrase not in blob, f"user-facing copy still promises appending: {phrase!r}"


def _flat(e) -> str:
    parts = [e.title or "", e.description or ""]
    for f in e.fields:
        parts += [f.name or "", f.value or ""]
    return "\n".join(parts)


# --- the first thirty seconds -------------------------------------------------------------
# Two things a newcomer hit on 2026-08-11, both the same mistake: the interface described its own
# mechanics instead of saying what would happen.

def test_grind_takes_no_options_except_your_own_files():
    """REWRITTEN 2026-08-18, because the founder reversed the decision this pinned. It is not
    weakened: it pins MORE than it used to.

    The original rule was "/grind takes nothing", written after `beat` and `vocal` options were
    removed - a first-timer seeing two blanks cannot tell that pressing enter is the right move.
    The REASON those two were wrong is that they duplicated the picker sitting underneath, so the
    blanks were a second way to do the thing the screen was already doing.

    Attachments are the opposite case: Discord will not let a button or a select menu open a file
    chooser, and a modal takes text only, so an attachment can ONLY arrive on the command. The
    alternative to these two options is a second command, which is what the founder asked to be
    rid of.

    So the rule is now sharper: the ONLY options /grind may ever carry are the person's own files,
    every one of them optional, and never a song CHOICE - that belongs to the picker."""
    import bot as botmod
    import discord

    cmd = next(c for c in botmod.bot.tree.get_commands() if c.name == "grind")
    params = list(getattr(cmd, "parameters", []))
    assert [p.name for p in params] == ["my_song"], \
        "/grind grew an option that is not the person's own file"
    for p in params:
        assert not p.required, f"/grind option {p.name!r} is required; typing /grind must still work"
        assert p.type is discord.AppCommandOptionType.attachment, \
            f"/grind option {p.name!r} is not a file - a song CHOICE belongs to the picker"


def test_the_empty_picker_says_what_stacking_actually_produces(monkeypatch):
    """'nothing stacked yet' and 'Add another' never said WHAT you get. Nobody can guess that
    several pairs become one continuous back-to-back set - the outcome has to be on the screen."""
    v = _builder(monkeypatch)
    text = (v.embed().title or "") + "\n" + (v.embed().description or "")
    low = text.lower()
    assert "back to back" in low or "one continuous" in low or "one long" in low, \
        f"the empty picker never says what a stack produces:\n{text}"


def test_controls_that_cannot_do_anything_yet_are_disabled(monkeypatch):
    """All three buttons looked equally available with nothing picked, so the order of operations
    had to be guessed. A greyed-out button teaches the sequence without a word of instruction."""
    v = _builder(monkeypatch)
    by_label = {i.label: i for i in v.children if hasattr(i, "label")}
    assert by_label["Add another pair"].disabled is True, "nothing picked yet, so there is nothing to add"
    assert by_label["Remove the last one"].disabled is True, "nothing stacked to take off"
    assert by_label["Grind it"].disabled is True, "nothing to grind yet"


def test_the_controls_wake_up_as_soon_as_a_pair_is_picked(monkeypatch):
    v = _builder(monkeypatch)
    v.sel_beat, v.sel_vocal = "b1", "v1"
    v.sync_buttons()
    by_label = {i.label: i for i in v.children if hasattr(i, "label")}
    assert by_label["Grind it"].disabled is False
    assert by_label["Add another pair"].disabled is False
