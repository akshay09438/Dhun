"""Three founder requests from 2026-08-14, pinned.

1. `/grind` belongs in `#get-shit-done` and the listening rooms - NOT in `#best-mixes`, which shares
   the grind category but is the finished-work wall.
2. `/invitefriend` and `/applications` must be HIDDEN from ordinary members, not merely refused
   after the fact - the founder saw both sitting in the picker from a plain member account.
3. The welcome a newcomer gets under 30 members must not mention a form (there isn't one), and must
   name the real room rather than "the grind channel", which has never existed.
"""

from __future__ import annotations

import types

import pytest

import bot as botmod
import door


# --------------------------------------------------------------------- 1. where /grind works
def _interaction(channel, *, in_room=False, monkeypatch=None):
    guild = types.SimpleNamespace(text_channels=[channel])
    user = types.SimpleNamespace(id=7)
    if monkeypatch is not None:
        monkeypatch.setattr(botmod.booth, "room_of", lambda _u: "a room" if in_room else None)
    return types.SimpleNamespace(channel=channel, guild=guild, user=user)


def _chan(cid, cat_id, name="c"):
    return types.SimpleNamespace(id=cid, name=name,
                                 category=types.SimpleNamespace(id=cat_id), category_id=cat_id)


def test_grind_is_allowed_in_the_workbench_channel(monkeypatch):
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 100, raising=False)
    monkeypatch.setattr(botmod.CFG, "fresh_grinds_channel_id", 999, raising=False)
    ch = _chan(200, 100, "get-shit-done")
    assert botmod._grinding_allowed_here(_interaction(ch, monkeypatch=monkeypatch)) is None


def test_grind_is_REFUSED_in_the_showcase_even_though_it_shares_the_category(monkeypatch):
    """The regression this whole change exists for: #best-mixes sits in the grind category, so the
    old category-wide rule allowed grinding straight into the showcase wall."""
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 100, raising=False)
    monkeypatch.setattr(botmod.CFG, "fresh_grinds_channel_id", 999, raising=False)
    showcase = _chan(999, 100, "best-mixes")
    msg = botmod._grinding_allowed_here(_interaction(showcase, monkeypatch=monkeypatch))
    assert msg is not None, "grinding into #best-mixes must be refused"
    assert "best-mixes" not in msg, "the refusal must not offer the showcase as a place to grind"


def test_a_listening_room_still_works(monkeypatch):
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 100, raising=False)
    monkeypatch.setattr(botmod.CFG, "fresh_grinds_channel_id", 999, raising=False)
    elsewhere = _chan(300, 555, "general")
    assert botmod._grinding_allowed_here(
        _interaction(elsewhere, in_room=True, monkeypatch=monkeypatch)) is None


def test_an_unrelated_channel_is_still_refused(monkeypatch):
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 100, raising=False)
    monkeypatch.setattr(botmod.CFG, "fresh_grinds_channel_id", 999, raising=False)
    elsewhere = _chan(300, 555, "general")
    assert botmod._grinding_allowed_here(
        _interaction(elsewhere, monkeypatch=monkeypatch)) is not None


def test_no_showcase_configured_leaves_the_old_behaviour_alone(monkeypatch):
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 100, raising=False)
    monkeypatch.setattr(botmod.CFG, "fresh_grinds_channel_id", None, raising=False)
    ch = _chan(200, 100)
    assert botmod._grinding_allowed_here(_interaction(ch, monkeypatch=monkeypatch)) is None


# --------------------------------------------------------------- 2. moderator commands are hidden
@pytest.mark.parametrize("name", ["invitefriend", "applications", "setup"])
def test_moderator_commands_are_hidden_from_ordinary_members(name):
    """`default_permissions` is what makes DISCORD hide a command. Without it the command still
    appears in every member's picker and only refuses once they run it."""
    cmd = botmod.bot.tree.get_command(name)
    assert cmd is not None, f"/{name} is not registered"
    perms = cmd.default_permissions
    assert perms is not None, f"/{name} has no default_permissions, so members can see it"
    assert perms.manage_guild, f"/{name} is not gated on Manage Server"


def test_grind_is_NOT_hidden():
    """The counterpart: /grind is the whole point of the server and must stay visible to everyone."""
    assert botmod.bot.tree.get_command("grind").default_permissions is None


# ------------------------------------------------------------------------- 3. the welcome copy
def test_the_open_door_welcome_never_mentions_a_form(monkeypatch):
    monkeypatch.setattr(door.CFG, "grinder_channel_id", 4242, raising=False)
    msg = door.open_door_welcome()
    assert "form" not in msg.lower(), f"the under-30 welcome still mentions a form: {msg!r}"


def test_the_welcome_points_at_the_real_room_not_a_made_up_name(monkeypatch):
    monkeypatch.setattr(door.CFG, "grinder_channel_id", 4242, raising=False)
    assert door.grind_channel_mention() == "<#4242>"
    for msg in (door.open_door_welcome(), door.vouched_welcome()):
        assert "<#4242>" in msg, f"copy does not link the real room: {msg!r}"
        assert "the grind channel" not in msg, \
            f"copy still sends people to 'the grind channel', a room that does not exist: {msg!r}"


def test_the_welcome_still_tells_them_what_to_actually_do(monkeypatch):
    """Removing the form line must not remove the instruction - the point of the message."""
    monkeypatch.setattr(door.CFG, "grinder_channel_id", 4242, raising=False)
    msg = door.open_door_welcome()
    assert "/grind" in msg and "You are in" in msg


def test_the_mention_degrades_to_words_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(door.CFG, "grinder_channel_id", None, raising=False)
    assert door.grind_channel_mention() == "the grind channel"
