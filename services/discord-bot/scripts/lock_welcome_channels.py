"""Make the three welcome/notice channels read-only for members.

    python services/discord-bot/scripts/lock_welcome_channels.py            # DRY RUN (default)
    python services/discord-bot/scripts/lock_welcome_channels.py --apply    # actually do it
    python services/discord-bot/scripts/lock_welcome_channels.py --undo --apply   # reverse it

THE PROBLEM. `#read-this-first`, `#announcements` and `#rules` are notices - one side talking. But
`@Member` can currently TYPE in all three (measured on the live server 2026-08-14: `@everyone` is
read-only there, `@Member` is not, because @Member simply inherits Send Messages from the role's
base permissions and no channel overwrite contradicts it). So the rules can be argued with inside
the rules, and an announcement can be buried under replies. Founder, 2026-08-14: these should be
locked for users.

THE FIX, and it is one rule per channel: deny `send_messages` to `@Member` on those three. Reading,
history, reactions are all untouched - people can still react to an announcement, just not reply
underneath it.

WHY THIS IS SAFE, given the 2026-08-13 incident that half-locked the live server:

  * it touches THREE channels and ONE role, and NEVER `@everyone` - the failure last time was an
    `@everyone` deny landing before the `@Member` grant, which locked the bot out of the channel it
    was editing. Nothing here writes an `@everyone` overwrite at all;
  * it denies ONLY `send_messages`. `view_channel` is not touched, so nobody can lose sight of a
    channel - the worst case is somebody cannot post in a notice board;
  * the owner and any Administrator keep posting regardless: Discord's Administrator bypasses
    channel overwrites. The founder cannot lock themselves out of their own announcements;
  * Grinder itself holds Administrator, so it can still post the announcements it is supposed to
    post in those channels;
  * every change is printed BEFORE it happens, and `--undo` reverses exactly the same three rules.

Channels are matched by NAME here rather than by a configured id, because these three have no ids
in `.env` - and a name that does not match is reported and SKIPPED, never guessed at.

Plain ASCII output only: this machine's console cannot encode anything else, and that has already
cost this project three separate incidents.
"""

import asyncio
import os
import sys
from pathlib import Path

_BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BOT))

import botconfig  # noqa: E402

CFG = botconfig.load_config()

import discord  # noqa: E402

APPLY = "--apply" in sys.argv
UNDO = "--undo" in sys.argv

MEMBER_ROLE = "Member"
TARGETS = ["read-this-first", "announcements", "rules"]

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
_failed = False


def say(s=""):
    print(s, flush=True)


def desired_overwrite(existing, *, undo: bool):
    """Return the @Member overwrite we want, built BY EDITING the existing one.

    THE BUG THIS EXISTS TO PREVENT (2026-08-14, and it hid all three channels from every member).
    `set_permissions(role, send_messages=False)` does NOT edit an overwrite - it REPLACES it with
    one built from exactly the keyword arguments given. `lock_the_door.py` had previously denied
    `read_messages` to `@everyone` and granted it back to `@Member` on every channel, so the
    @Member overwrite carried a load-bearing `read_messages=True`. Passing only `send_messages`
    wiped it, @Member fell back to the @everyone deny, and the rooms disappeared entirely instead
    of going read-only.

    So: take what is there, change only the one field, hand the whole object back. Anything else
    already set - now or in future - survives untouched.
    """
    ov = discord.PermissionOverwrite(**{k: v for k, v in existing if v is not None})
    ov.send_messages = None if undo else False
    # AND ASSERT VISIBILITY, do not merely preserve it. These three are notice boards: a member who
    # cannot read them is worse off than before we started, which is exactly what happened. On this
    # server `@everyone` is denied `read_messages` everywhere (lock_the_door.py), so `@Member` needs
    # an explicit allow or the room is invisible - and on the live server that allow has ALREADY
    # been destroyed, so preserving what is there would faithfully preserve the broken state.
    ov.read_messages = True
    return ov


def is_now_as_wanted(existing, *, undo: bool) -> bool:
    """True when this channel already matches the intent, so it can be skipped."""
    return existing.send_messages is (None if undo else False)


async def run_for(guild):
    global _failed
    member = discord.utils.get(guild.roles, name=MEMBER_ROLE)
    if member is None:
        say(f"  no @{MEMBER_ROLE} role in {guild.name} - nothing to do, and nothing changed.")
        _failed = True
        return

    say(f"=== {guild.name} ===")
    say(f"  {'REVERSING' if UNDO else 'LOCKING'} for @{MEMBER_ROLE}"
        f"{'' if APPLY else '   (DRY RUN)'}")
    say()

    for name in TARGETS:
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch is None:
            say(f"  SKIP  #{name}: no channel with that name. Not guessing at another one.")
            _failed = True
            continue

        p_before = ch.permissions_for(member)
        current_ov = ch.overwrites_for(member)

        if is_now_as_wanted(current_ov, undo=UNDO) and p_before.view_channel:
            say(f"  ok    #{name:<18} already {'unlocked' if UNDO else 'read-only'} and visible")
            continue

        new_ov = desired_overwrite(current_ov, undo=UNDO)
        say(f"  {'UNLOCK' if UNDO else 'LOCK  '} #{name:<18} "
            f"can see: {p_before.view_channel} -> {new_ov.read_messages is not False}   "
            f"can type: {p_before.send_messages} -> {'inherited' if UNDO else False}")
        if APPLY:
            try:
                await ch.set_permissions(
                    member, overwrite=new_ov,
                    reason="Founder 2026-08-14: notice channels are read-only for members")
            except discord.Forbidden:
                say(f"        REFUSED on #{name}: Grinder lacks Manage Permissions there.")
                _failed = True
            except discord.HTTPException as e:
                say(f"        FAILED on #{name}: {e}")
                _failed = True

    say()
    say("  --- state as Discord reports it now ---")
    for name in TARGETS:
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch is None:
            continue
        p = ch.permissions_for(member)
        flag = "" if p.view_channel else "   <-- INVISIBLE, THIS IS WRONG"
        say(f"    #{name:<18} @{MEMBER_ROLE} can SEE: {str(p.view_channel):<5} "
            f"can TYPE: {str(p.send_messages):<5} can REACT: {str(p.add_reactions):<5}{flag}")


@client.event
async def on_ready():
    try:
        say(f"logged in as {client.user}")
        say()
        for g in client.guilds:
            await run_for(g)
        say()
        if not APPLY:
            say("DRY RUN - nothing was changed.")
            say("  to do it:      ...lock_welcome_channels.py --apply")
            say("  to reverse it: ...lock_welcome_channels.py --undo --apply")
        elif _failed:
            say("DONE, WITH PROBLEMS - read the lines above.")
        else:
            say("DONE. Reverse it any time with --undo --apply.")
    finally:
        await client.close()


if not CFG.token:
    say("no bot token configured")
    raise SystemExit(1)
asyncio.run(client.start(CFG.token))
