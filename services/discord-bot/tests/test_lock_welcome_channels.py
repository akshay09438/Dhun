"""Locking a notice channel must make it READ-ONLY, never invisible.

THE INCIDENT, 2026-08-14. `lock_welcome_channels.py --apply` was run against the live server and
hid `#read-this-first`, `#announcements` and `#rules` from every member instead of muting them.
Cause: `set_permissions(role, send_messages=False)` REPLACES the overwrite rather than editing it.
`lock_the_door.py` had denied `read_messages` to `@everyone` and granted it back to `@Member` on
every channel, so the @Member overwrite carried a load-bearing `read_messages=True`. Passing only
`send_messages` wiped it, @Member fell back to the @everyone deny, and three rooms vanished.

The founder saw it before any test did, which is what these are for.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import discord
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lock_welcome_channels.py"


@pytest.fixture(scope="module")
def mod():
    """Import the script without running its `asyncio.run(...)` tail."""
    src = _SCRIPT.read_text(encoding="utf-8")
    src = src.split("if not CFG.token:")[0]          # drop the run-it-for-real tail
    src = src.replace("CFG = botconfig.load_config()", "CFG = None")
    # The script resolves its own location from __file__; exec() does not supply one.
    ns: dict = {"__file__": str(_SCRIPT), "__name__": "lock_welcome_channels_under_test"}
    exec(compile(src, str(_SCRIPT), "exec"), ns)      # noqa: S102 — importing a __main__ script
    return type("M", (), ns)


def _door_style_overwrite():
    """What lock_the_door.py leaves behind on every channel: members can see it."""
    return discord.PermissionOverwrite(read_messages=True)


# ------------------------------------------------------------------ the regression itself
def test_locking_keeps_the_channel_VISIBLE(mod):
    """The whole incident in one assertion."""
    out = mod.desired_overwrite(_door_style_overwrite(), undo=False)
    assert out.read_messages is True, (
        "locking wiped the read_messages grant, so the channel disappears for members "
        "instead of going read-only - this is the 2026-08-14 regression"
    )


def test_locking_actually_stops_them_typing(mod):
    out = mod.desired_overwrite(_door_style_overwrite(), undo=False)
    assert out.send_messages is False


def test_undo_restores_typing_and_still_keeps_it_visible(mod):
    out = mod.desired_overwrite(_door_style_overwrite(), undo=True)
    assert out.send_messages is None, "undo must return send_messages to inherited"
    assert out.read_messages is True, "undo must not hide the channel either"


# ------------------------------------------------------------------ it must not eat anything else
def test_unrelated_permissions_on_the_overwrite_survive(mod):
    """The general rule the incident taught: edit the overwrite, never rebuild it from scratch."""
    existing = discord.PermissionOverwrite(
        read_messages=True, add_reactions=True, attach_files=False, manage_messages=True)
    out = mod.desired_overwrite(existing, undo=False)
    assert out.read_messages is True
    assert out.add_reactions is True
    assert out.attach_files is False
    assert out.manage_messages is True
    assert out.send_messages is False


def test_visibility_is_ASSERTED_not_merely_preserved(mod):
    """The second half of the same incident.

    Editing-not-replacing fixes the script going forward, but on a channel whose grant was ALREADY
    destroyed, faithfully preserving what is there preserves the breakage. These three are notice
    boards - the entire point is that members read them - so locking one must guarantee it is
    readable, starting from whatever state it is in now.
    """
    already_broken = discord.PermissionOverwrite(send_messages=False)   # the live state, post-bug
    out = mod.desired_overwrite(already_broken, undo=False)
    assert out.read_messages is True, "a notice board nobody can read is worse than an unlocked one"
    assert out.send_messages is False


def test_undo_leaves_the_channel_readable_too(mod):
    already_broken = discord.PermissionOverwrite(send_messages=False)
    out = mod.desired_overwrite(already_broken, undo=True)
    assert out.read_messages is True and out.send_messages is None


# ------------------------------------------------------------------ the skip check
def test_already_locked_and_visible_is_skipped(mod):
    ov = discord.PermissionOverwrite(read_messages=True, send_messages=False)
    assert mod.is_now_as_wanted(ov, undo=False) is True


def test_a_locked_channel_is_not_considered_done_when_undoing(mod):
    ov = discord.PermissionOverwrite(read_messages=True, send_messages=False)
    assert mod.is_now_as_wanted(ov, undo=True) is False


def test_the_script_never_writes_an_everyone_overwrite(mod):
    """The 2026-08-13 incident: an @everyone deny landing first locked the bot out of the channel
    it was editing. This script must only ever touch the @Member role."""
    src = _SCRIPT.read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]          # ignore the docstring, which discusses @everyone
    assert "default_role" not in body, "the script must never write an @everyone overwrite"
