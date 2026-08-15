"""Make Grinder a NORMAL, OPEN Discord server. Dry run by default.

    python scripts/open_the_server.py            # DRY RUN - prints every change, touches nothing
    python scripts/open_the_server.py --apply    # actually do it

FOUNDER, 2026-08-15: "remove the lobby/door everything - normal open to all discord server, as they
enter the server, the first thing they see is the read-this-first channel."

This REVERSES the 2026-08-13 lockdown (`lock_the_door.py`), which denied `read_messages` to
`@everyone` on every category and every channel so that an unapproved stranger could see nothing but
the lobby. With the door gone that lockdown is exactly backwards: it is what makes `#the-door` the
only room a newcomer can see, and therefore the room Discord drops them into and keeps returning
them to.

WHAT IT DOES, and nothing else:

  * every CATEGORY and every ordinary CHANNEL  -> clear the `@everyone` view denial, so the server
    is visible to anyone who joins. Set to NEUTRAL (None), not to an explicit allow: neutral is how
    an ordinary Discord server looks, and it lets a future category-level rule work normally.
  * `#read-this-first`                          -> additionally deny `send_messages` to `@everyone`,
    so it stays a notice board rather than becoming a chat room. It sits at position 0, so it is
    what a newcomer lands on.
  * `#the-door` and `#applications`             -> deny `view_channel` to `@everyone`. The door is
    finished; these two rooms are kept (deleting a channel destroys its history and cannot be
    undone) but nobody meets them.

HOW IT EDITS A PERMISSION, which is the part that has gone wrong here before. `set_permissions(t,
**kwargs)` REPLACES the whole overwrite - on 2026-08-14 that destroyed a `read_messages` grant and
silently hid three channels. So this reads `overwrites_for(target)`, changes ONLY the named fields
on that object, and writes the whole object back. Every other field is carried through untouched,
and the printout shows every field before and after so a change that alters something unintended is
visible rather than invisible.

Plain ASCII output only - this machine's console cannot encode anything else.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402

from botconfig import load_config  # noqa: E402

CFG = load_config()

HIDDEN_FROM_EVERYONE = {"the-door", "applications"}
READ_ONLY_FOR_EVERYONE = {"read-this-first"}


def _fields(ow) -> str:
    allow = [f for f, v in ow if v is True]
    deny = [f for f, v in ow if v is False]
    return f"allow={allow or '-'} deny={deny or '-'}"


async def main(apply: bool) -> int:
    client = discord.Client(intents=discord.Intents.default())
    await client.login(CFG.token)
    try:
        guild = await client.fetch_guild(CFG.guild_id)
        everyone = guild.default_role
        channels = sorted(await guild.fetch_channels(), key=lambda c: (c.position, str(c.type)))

        print("=" * 78)
        print(f"{'APPLYING' if apply else 'DRY RUN - nothing will be changed'}: open the server")
        print("=" * 78)
        planned = 0
        for ch in channels:
            name = getattr(ch, "name", "?")
            ow = ch.overwrites_for(everyone)          # READ the whole existing overwrite
            before = _fields(ow)

            if name in HIDDEN_FROM_EVERYONE:
                ow.view_channel = False               # change ONLY this field
                intent = "hide from everyone (the door is finished)"
            else:
                ow.view_channel = None                # neutral: an ordinary, visible channel
                intent = "visible to anyone who joins"
                if name in READ_ONLY_FOR_EVERYONE:
                    ow.send_messages = False
                    intent += ", but read-only"

            after = _fields(ow)
            if before == after:
                print(f"  #{name:<20} already correct    {before}")
                continue
            planned += 1
            kind = "CATEGORY" if isinstance(ch, discord.CategoryChannel) else str(ch.type)
            print(f"  #{name:<20} [{kind}]  {intent}")
            print(f"       @everyone before : {before}")
            print(f"       @everyone after  : {after}")
            if apply:
                await ch.set_permissions(everyone, overwrite=ow,
                                         reason="Founder 2026-08-15: normal open server, no door")
                print("       APPLIED")

        print()
        print(f"  channels needing a change: {planned}")
        if not apply:
            print("  DRY RUN - nothing was changed. Re-run with --apply to do it.")
        else:
            print("  Applied. Now verify with a SEPARATE process:")
            print("     python scripts/landing_probe.py")
            print("  (never trust this script's own closing read - on 2026-08-14 a deleting")
            print("   script's final read still listed a channel it had just deleted.)")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))
