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

        before = ch.permissions_for(member).send_messages
        want = None if UNDO else False          # None = clear the overwrite, i.e. back to inherited
        current_ov = ch.overwrites_for(member)

        if (not UNDO and current_ov.send_messages is False) or (UNDO and current_ov.send_messages is None):
            say(f"  ok    #{name:<18} already {'unlocked' if UNDO else 'locked'} - no change needed")
            continue

        say(f"  {'UNLOCK' if UNDO else 'LOCK  '} #{name:<18} @{MEMBER_ROLE} can type now: {before}"
            f"  ->  {'True (inherited)' if UNDO else 'False'}")
        if APPLY:
            try:
                await ch.set_permissions(
                    member, send_messages=want,
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
        m = ch.permissions_for(member).send_messages
        e = ch.permissions_for(guild.default_role).send_messages
        say(f"    #{name:<18} @{MEMBER_ROLE} can type: {str(m):<5}   @everyone can type: {e}")


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
