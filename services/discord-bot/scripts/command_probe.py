"""Ask DISCORD which commands are registered, and who can see each one. READ-ONLY.

Why this exists rather than a glance at the member list: `Member.status` reads `offline` for every
member without the privileged presences intent, which on 2026-08-14 cost a healthy bot being killed
and debugged. The honest "is Grinder actually up and usable" check is functional - what has it
registered with Discord, and is each command visible to the people who should see it.

It deliberately prints `default_member_permissions` - the field that decides whether a command is
HIDDEN from ordinary members - as well as the name, because a probe that prints only the thing you
were looking at is how three channels got hidden in silence on 2026-08-14.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402

from botconfig import load_config  # noqa: E402

CFG = load_config()

MOD_ONLY = {"setup", "invitefriend", "applications"}


async def main() -> int:
    client = discord.Client(intents=discord.Intents.default())
    await client.login(CFG.token)
    try:
        app = await client.application_info()
        guild = discord.Object(id=CFG.guild_id) if CFG.guild_id else None
        cmds = await client.http.get_guild_commands(app.id, CFG.guild_id) if guild else []
        print("=" * 72)
        print(f"Grinder is REGISTERED with Discord — {len(cmds)} commands on guild {CFG.guild_id}")
        print("=" * 72)
        print(f"{'command':<18}{'hidden from members?':<24}default_member_permissions")
        print("-" * 72)
        wrong = []
        for c in sorted(cmds, key=lambda d: d["name"]):
            perms = c.get("default_member_permissions")
            hidden = perms is not None and perms != "0"
            should_hide = c["name"] in MOD_ONLY
            flag = "" if hidden == should_hide else "   <-- NOT AS INTENDED"
            if flag:
                wrong.append(c["name"])
            print(f"/{c['name']:<17}{('YES' if hidden else 'no'):<24}{perms}{flag}")
        print()
        print(f"moderator-only and hidden : "
              f"{sorted(n for n in MOD_ONLY if n in {c['name'] for c in cmds})}")
        print(f"visible to everyone       : "
              f"{sorted(c['name'] for c in cmds if c['name'] not in MOD_ONLY)}")
        if wrong:
            print(f"\nWRONG VISIBILITY: {wrong}")
            return 1
        print("\nEvery command's visibility matches what it should be.")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
