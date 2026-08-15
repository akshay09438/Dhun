"""Wipe a channel's messages so newcomers arrive to a clean room. DRY RUN by default.

    python scripts/clear_channels.py                       # DRY RUN - counts only, deletes nothing
    python scripts/clear_channels.py --apply               # actually delete
    python scripts/clear_channels.py --channels a,b        # override the list
    python scripts/clear_channels.py --wipe-intro          # also delete the intro post

FOUNDER, 2026-08-15: "clear the Get Shit Done channel with the general channel so that when users
come, it's new... Keep the best mix channels as they are."

THIS IS THE MOST DESTRUCTIVE SCRIPT IN THE REPO. Deleted Discord messages cannot be recovered by
anyone, including Discord. So:

  * DRY RUN IS THE DEFAULT, and it prints a per-channel count, the oldest and newest message, and
    who wrote them, so the founder sees exactly what is about to go;
  * the channels are named EXACTLY, never by substring - substring matching bit this project twice
    in one evening (`Water` also matches `WATERmelon Sugar`), and here a wrong match destroys
    somebody's history;
  * NEVER_TOUCH is a hard block checked before anything else. `#best-mixes` is the founder's
    showcase and `#read-this-first` is the first thing every newcomer now sees; wiping either would
    be unrecoverable and is refused even if explicitly asked for on the command line.

Discord's bulk delete only works on messages under 14 days old. Anything older has to go one at a
time, which is slow and rate-limited - so the dry run reports how many fall into each bucket rather
than letting the founder discover it halfway through.

Plain ASCII output only.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402

from botconfig import load_config  # noqa: E402

CFG = load_config()

DEFAULT_CLEAR = ["get-shit-done", "general"]
# Refused even if named explicitly. The showcase is the founder's kept work; read-this-first is the
# landing channel every newcomer now sees first.
NEVER_TOUCH = {"best-mixes", "read-this-first"}


async def main(apply: bool, names: list[str], keep_intro: bool = True) -> int:
    refused = [n for n in names if n in NEVER_TOUCH]
    if refused:
        print(f"REFUSING: {refused} are on the never-touch list. Nothing was done.")
        return 1

    client = discord.Client(intents=discord.Intents.default())
    await client.login(CFG.token)
    try:
        guild = await client.fetch_guild(CFG.guild_id)
        by_name = {c.name: c for c in await guild.fetch_channels()
                   if isinstance(c, discord.TextChannel)}
        missing = [n for n in names if n not in by_name]
        if missing:
            print(f"REFUSING: no channel is named exactly {missing}. Nothing was done.")
            return 1

        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
        print("=" * 78)
        print(f"{'APPLYING - messages will be DELETED FOREVER' if apply else 'DRY RUN - nothing will be deleted'}")
        print("=" * 78)
        for name in names:
            ch = by_name[name]
            msgs = [m async for m in ch.history(limit=None)]
            # KEEP THE INTRO (founder decision, 2026-08-15). The oldest message in each of these
            # rooms is Grinder's own "what this channel is for" post, written when the server was
            # built. Wiping it leaves a newcomer in a blank room with no idea what it is, which is
            # the opposite of the "arrives feeling new" the clear-out is for. Kept only when the
            # OLDEST message is the bot's own - a person's message is never treated as an intro.
            intro = None
            if keep_intro and msgs and msgs[-1].author.id == client.user.id:
                intro = msgs[-1]
                msgs = msgs[:-1]
                print(f"  (keeping the intro post in #{name}: "
                      f"{intro.created_at:%Y-%m-%d %H:%M} by {intro.author.name})")
            recent = [m for m in msgs if m.created_at > cutoff]
            old = [m for m in msgs if m.created_at <= cutoff]
            authors: dict[str, int] = {}
            for m in msgs:
                authors[m.author.name] = authors.get(m.author.name, 0) + 1
            print(f"  #{name}")
            print(f"     to delete           : {len(msgs)}")
            print(f"     under 14 days (fast): {len(recent)}")
            print(f"     older (one by one)  : {len(old)}")
            if msgs:
                print(f"     oldest             : {msgs[-1].created_at:%Y-%m-%d %H:%M} by {msgs[-1].author.name}")
                print(f"     newest             : {msgs[0].created_at:%Y-%m-%d %H:%M} by {msgs[0].author.name}")
                print(f"     who wrote them     : {authors}")
            if not apply:
                print()
                continue
            deleted = 0
            for chunk in (recent[i:i + 100] for i in range(0, len(recent), 100)):
                await ch.delete_messages(chunk)
                deleted += len(chunk)
            for m in old:
                try:
                    await m.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
            print(f"     DELETED            : {deleted}")
            print()

        kept = sorted(set(by_name) - set(names))
        print(f"  UNTOUCHED: {kept}")
        if not apply:
            print()
            print("  DRY RUN - nothing was deleted. Re-run with --apply to do it.")
            print("  This cannot be undone. Discord keeps no copy.")
        else:
            print()
            print("  Done. Verify with a SEPARATE process - this script's own closing read is not")
            print("  evidence (on 2026-08-14 a deleting script still listed what it had deleted).")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    argv = sys.argv[1:]
    chosen = DEFAULT_CLEAR
    if "--channels" in argv:
        chosen = [s.strip() for s in argv[argv.index("--channels") + 1].split(",") if s.strip()]
    raise SystemExit(asyncio.run(main("--apply" in argv, chosen,
                                     keep_intro="--wipe-intro" not in argv)))
