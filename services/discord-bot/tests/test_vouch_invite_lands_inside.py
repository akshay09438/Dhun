"""A vouched friend must not be dropped into the lobby they were promised they could skip.

THE BUG THE FOUNDER FOUND, 2026-08-15, with a screenshot. Opening the server showed them
`#the-door` - the lobby - even though that channel is NOT in their sidebar and they cannot post in
it. The page they were looking at was two days stale.

MEASURED ON THE LIVE SERVER BEFORE ANYTHING WAS CHANGED, and this is what makes the cause certain:
the permissions are RIGHT. Discord's own computation for that account says `#the-door` view=False,
`#read-this-first` view=True, and the first channel they can see is `#read-this-first`. So the
sidebar was correct and the server was correct.

THE ROOT CAUSE IS THE INVITE. A Discord invite is created against a CHANNEL, and that channel is
where the joiner's client lands - and stays, because Discord reopens the last channel a person read
in a server. `/invitefriend` created its single-use link against `CFG.door_channel_id`:

    channel = interaction.guild.get_channel(CFG.door_channel_id) or interaction.channel

So the sequence was: friend clicks the vouch link -> lands in `#the-door` -> the bot grants
`@Member` -> `@Member` is denied `view_channel` on `#the-door` -> the lobby vanishes from their
sidebar, and their client goes on reopening a channel that is no longer there. A live invite doing
exactly this was found on the server (`PUWVqKfC -> #the-door`, unused, waiting for the next friend).

The command's own docstring says "Their friend clicks the link and is in - no lobby, no five
questions, no waiting." It did the one thing it promised not to.

THE RULE, which is what these tests actually pin: an invite must never target a channel the joiner
will lose access to the moment they are let in. Chosen by PERMISSION, not by name, so renaming
`#read-this-first` - which the founder does - cannot quietly reintroduce this.
"""
import asyncio
import os
import types

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import discord  # noqa: E402

import door  # noqa: E402


class _Role:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


class _Chan:
    """A text channel that answers permissions_for() from a simple visible-to set."""

    def __init__(self, name, position, visible_to):
        self.name = name
        self.position = position
        self.id = 1000 + position
        self._visible_to = set(visible_to)

    def permissions_for(self, obj):
        return types.SimpleNamespace(view_channel=getattr(obj, "name", None) in self._visible_to)

    def __str__(self):
        return self.name


class _Guild:
    def __init__(self, channels, roles):
        self.text_channels = channels
        self.roles = roles

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)


def _server(door_visible_to_member=False):
    """The founder's real layout: the lobby sits BELOW everything and is hidden from members."""
    member, everyone = _Role("Member"), _Role("@everyone")
    lobby_viewers = ["Member", "@everyone"] if door_visible_to_member else ["@everyone"]
    channels = [
        _Chan("read-this-first", 0, ["Member", "@everyone"]),
        _Chan("get-shit-done", 4, ["Member"]),
        _Chan("the-door", 8, lobby_viewers),
        _Chan("applications", 9, []),
    ]
    return _Guild(channels, [everyone, member])


# --- the rule ------------------------------------------------------------------------------

def test_the_arrival_channel_is_one_a_member_can_still_see():
    """The whole fix in one line: pick where somebody lands by what they will be able to VIEW."""
    guild = _server()
    assert door.arrival_channel(guild).name == "read-this-first"


def test_the_arrival_channel_is_never_the_lobby():
    """The lobby is the one channel a let-in person provably loses. It can never be the target."""
    assert door.arrival_channel(_server()).name != "the-door"


def test_it_is_chosen_by_permission_not_by_name():
    """The founder renames channels - `the-grinder` -> `#get-shit-done`, `fresh-grinds` ->
    `#best-mixes`. A fix that matched the string "read-this-first" would silently rot the next
    time they renamed something. Rename the welcome channel and the rule must still hold."""
    guild = _server()
    guild.text_channels[0].name = "start-here-please"
    assert door.arrival_channel(guild).name == "start-here-please"


def test_a_lobby_that_members_CAN_see_is_still_not_chosen_over_a_higher_channel():
    """Order still decides among the channels a member can see; the lobby sits at the bottom."""
    guild = _server(door_visible_to_member=True)
    assert door.arrival_channel(guild).name == "read-this-first"


def test_no_member_role_means_no_guess():
    """With no @Member role the door feature is not really set up. Returning None lets the caller
    keep its existing behaviour rather than inventing a channel - guessing a channel is how a
    message lands in the wrong room in somebody else's server."""
    guild = _server()
    guild.roles = [_Role("@everyone")]
    assert door.arrival_channel(guild) is None


def test_nothing_visible_returns_none_rather_than_raising():
    """A misconfigured server must not take the vouch command down with it - a link that works is
    worth more than a crash."""
    guild = _server()
    for c in guild.text_channels:
        c._visible_to = set()
    assert door.arrival_channel(guild) is None


# --- the call site, which is where the bug actually lived ------------------------------------

def test_invitefriend_creates_the_link_against_the_arrival_channel(monkeypatch):
    """The bug, at the seam. `/invitefriend` passed the DOOR channel to create_invite, so the
    single-use link dropped the friend into the lobby. It must pass the arrival channel."""
    import bot as botmod

    guild = _server()
    lobby = guild.get_channel(1008)
    assert lobby.name == "the-door", "fixture sanity: 1008 is the lobby"

    used = {}

    async def _fake_create_vouch_invite(channel, created_by):
        used["channel"] = channel.name
        return "https://discord.gg/fake"

    monkeypatch.setattr(botmod.door, "create_vouch_invite", _fake_create_vouch_invite)
    monkeypatch.setattr(botmod.door, "is_open", lambda: True)
    monkeypatch.setattr(botmod.CFG, "door_channel_id", 1008, raising=False)

    sent = {}

    class _Resp:
        async def send_message(self, *a, **k):
            sent["msg"] = a[0] if a else k.get("content")

        async def defer(self, **k):
            pass

    class _Followup:
        async def send(self, *a, **k):
            sent["msg"] = a[0] if a else k.get("content")

    interaction = types.SimpleNamespace(
        guild=guild,
        channel=lobby,
        user=types.SimpleNamespace(id=7, guild_permissions=types.SimpleNamespace(manage_guild=True)),
        response=_Resp(),
        followup=_Followup(),
    )

    asyncio.run(botmod.invitefriend_cmd.callback(interaction))

    assert used.get("channel") == "read-this-first", (
        f"the vouch link was created against #{used.get('channel')} - a vouched friend is dropped "
        f"into the very lobby the command promises they skip")
