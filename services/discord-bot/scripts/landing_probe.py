"""WHAT DOES EACH PERSON SEE FIRST when they open this server? READ-ONLY. Changes nothing.

Discord has no "landing channel" setting. A client opens the last channel that person read, and
for somebody with no history it opens the FIRST channel they are allowed to view, in the server's
own top-to-bottom order. So "what do they land on" is answered by two things and nothing else:
the channel ORDER, and who can VIEW each one.

This prints, for every member: their roles, whether Administrator is in play (it bypasses every
channel overwrite, so an admin's view is never evidence of what a member sees), the complete
overwrite table for the channels in question - EVERY field that is set, not merely the one being
looked at - and the ordered list of channels that person can actually see, with the top one
called out as their landing channel.

The "every field" part is not decoration. On 2026-08-14 a probe printed only `send_messages`
after a permission change, reported success, and was blind to the fact that the same call had
destroyed a `read_messages` grant and hidden three channels from everybody.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402

from botconfig import load_config  # noqa: E402

CFG = load_config()
FOCUS = ("the-door", "applications", "read-this-first")


def _overwrite_rows(channel) -> list[str]:
    """Every explicit overwrite on this channel, and every field each one actually sets."""
    rows = []
    for target, ow in channel.overwrites.items():
        allow, deny = [], []
        for field, value in ow:
            if value is True:
                allow.append(field)
            elif value is False:
                deny.append(field)
        kind = "role" if isinstance(target, discord.Role) else "member"
        rows.append(f"      {kind:<7}{str(target):<26} allow={allow or '-'} deny={deny or '-'}")
    return rows or ["      (no explicit overwrites - inherits the category / @everyone)"]


async def main() -> int:
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)
    await client.login(CFG.token)
    try:
        guild = await client.fetch_guild(CFG.guild_id)
        channels = sorted(await guild.fetch_channels(), key=lambda c: (c.position, c.id))
        members = [m async for m in guild.fetch_members(limit=None)]

        print("=" * 78)
        print(f"{guild.name} - what each person opens first")
        print("=" * 78)
        print(f"  server features: {sorted(guild.features)}")
        try:
            ob = await client.http.request(
                discord.http.Route("GET", "/guilds/{guild_id}/onboarding", guild_id=guild.id))
            print(f"  onboarding (Server Guide) enabled: {ob.get('enabled')}")
            if ob.get("default_channel_ids"):
                names = [getattr(guild.get_channel(int(i)), "name", i)
                         for i in ob["default_channel_ids"]]
                print(f"  onboarding default channels     : {names}")
        except Exception as e:  # noqa: BLE001
            print(f"  onboarding: could not read ({type(e).__name__}: {e})")
        print()

        print("  CHANNEL ORDER (this is what decides the landing channel)")
        for c in channels:
            if isinstance(c, discord.CategoryChannel):
                print(f"    [{c.position:>2}] CATEGORY  {c.name}")
            else:
                mark = "  <-- focus" if c.name in FOCUS else ""
                print(f"    [{c.position:>2}] {str(c.type):<9} #{c.name}{mark}")
        print()

        print("  OVERWRITES ON THE CHANNELS THAT MATTER (every field that is set)")
        for c in channels:
            if getattr(c, "name", None) in FOCUS:
                print(f"    #{c.name}  (category: {getattr(c.category, 'name', None)}, pos {c.position})")
                for row in _overwrite_rows(c):
                    print(row)
        print()

        print("  EVERY MEMBER, AND WHAT THEY ACTUALLY OPEN")
        text_channels = [c for c in channels if isinstance(c, discord.TextChannel)]
        problems = 0
        for m in sorted(members, key=lambda m: (m.bot, m.name)):
            roles = [r.name for r in m.roles if r.name != "@everyone"]
            admin = m.guild_permissions.administrator
            owner = m.id == guild.owner_id
            visible = [c for c in text_channels if c.permissions_for(m).view_channel]
            landing = visible[0].name if visible else "(nothing visible)"
            tag = " BOT" if m.bot else ""
            print(f"    {m.name}{tag}")
            print(f"       roles      : {roles or ['(none)']}")
            print(f"       owner={owner}  administrator={admin}  <- admin bypasses every overwrite")
            for c in text_channels:
                if c.name in FOCUS:
                    p = c.permissions_for(m)
                    print(f"       #{c.name:<18} view={str(p.view_channel):<5} "
                          f"send={str(p.send_messages):<5} read_history={p.read_message_history}")
            print(f"       LANDS ON   : #{landing}")
            if landing == "the-door" and not m.bot and ("Member" in roles or admin or owner):
                print("       ^^^ WRONG: somebody who is already IN lands on the lobby")
                problems += 1
            print()

        print("=" * 78)
        print(f"members who would land on the lobby despite being in: {problems}")
        return 1 if problems else 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
