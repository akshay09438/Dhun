"""WHICH CHANNEL DOES EACH INVITE LINK DROP PEOPLE INTO? READ-ONLY. Changes nothing.

A Discord invite is not "to a server" - it is created against a specific CHANNEL, and that channel
is where the joiner's client lands and stays. So an invite made from #the-door drops every single
person who uses it into the lobby, and their client then remembers the lobby as the last place
they were, even after they are let in and the lobby is hidden from them.

This lists every invite with its target channel, its uses, and who made it, plus the widget and
vanity settings, which can also carry a channel.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402

from botconfig import load_config  # noqa: E402

CFG = load_config()


async def main() -> int:
    client = discord.Client(intents=discord.Intents.default())
    await client.login(CFG.token)
    try:
        guild = await client.fetch_guild(CFG.guild_id)
        print("=" * 78)
        print(f"{guild.name} - where every invite drops people")
        print("=" * 78)
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            print("  cannot read invites (needs Manage Server)")
            invites = []
        if not invites:
            print("  no active invites")
        landing = {}
        for i in invites:
            ch = getattr(i.channel, "name", "(none)")
            landing.setdefault(ch, 0)
            landing[ch] += 1
            print(f"  {i.code:<12} -> #{ch:<18} uses={i.uses:<4} max={i.max_uses} "
                  f"temp={i.temporary} by={getattr(i.inviter,'name','?')} expires={i.expires_at}")
        print()
        for ch, n in sorted(landing.items(), key=lambda kv: -kv[1]):
            flag = "   <-- THE LOBBY: everyone using these lands there" if ch == "the-door" else ""
            print(f"  {n} invite(s) drop people into #{ch}{flag}")
        print()
        try:
            v = await guild.vanity_invite()
            print(f"  vanity url: {v}")
        except Exception as e:  # noqa: BLE001
            print(f"  vanity url: none ({type(e).__name__})")
        try:
            w = await client.http.request(
                discord.http.Route("GET", "/guilds/{guild_id}/widget", guild_id=guild.id))
            cid = w.get("channel_id")
            name = getattr(guild.get_channel(int(cid)), "name", cid) if cid else None
            print(f"  widget enabled={w.get('enabled')} channel={name}")
        except Exception as e:  # noqa: BLE001
            print(f"  widget: could not read ({type(e).__name__})")
        sysc = getattr(guild, "system_channel", None)
        print(f"  system messages channel: {getattr(sysc, 'name', None)}")
        print(f"  rules channel          : {getattr(guild, 'rules_channel', None)}")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
