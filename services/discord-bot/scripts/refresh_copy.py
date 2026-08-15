"""Rewrite the pinned copy in every room, and NOTHING else.

    python services/discord-bot/scripts/refresh_copy.py            # show what would change
    python services/discord-bot/scripts/refresh_copy.py --apply    # actually write it

Why this exists rather than just `/setup`: `/setup` also CREATES every channel the plan describes.
The founder has renamed their rooms by hand (`the-grinder` is `get-shit-done`, `fresh-grinds` is
`best-mixes`, one Booth became two genre rooms), so a `/setup` run would add a second set of
channels beside the real ones. This touches nothing but the words.

What it can do:
  * EDIT a post Grinder itself wrote. Discord will not let a bot edit anyone else's message, so
    somebody's conversation cannot be lost here even in principle.
  * POST an intro into a room that has none (both listening rooms were blank).

It never creates, renames or deletes a channel, a role or an emoji.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# The founder's machine is Windows, where the console defaults to a codepage that cannot print
# anything outside Latin-1. `server_status.py` already carries this guard, and this script needed it
# just as badly: the moment the copy gained a 📣 the preview stopped dead half way through
# #read-this-first, exit code 0, no traceback. A REVIEW TOOL THAT SILENTLY TRUNCATES is worse than
# no preview at all - the rooms it stops before are the ones nobody reads before pressing --apply.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    except Exception:                                # noqa: BLE001 - best effort, never fatal
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                     # noqa: E402

import server_setup                                # noqa: E402
from botconfig import load_config                  # noqa: E402

CFG = load_config()
APPLY = "--apply" in sys.argv


def _ids() -> dict:
    return {"grind": CFG.grinder_channel_id, "showcase": CFG.fresh_grinds_channel_id}


def _preview(guild: discord.Guild) -> None:
    """Print the exact words that would go into each room, so they can be read before they land."""
    links = server_setup.resolve_links(guild, _ids())

    def name_of(ch, fallback):
        return f"#{ch.name}" if ch is not None else fallback

    print(f"\n{'=' * 74}\nDRY RUN - nothing has been written. Add --apply to write it.\n{'=' * 74}")
    print(f"\n  grind channel : {name_of(links.grind, 'NOT FOUND')}")
    print(f"  showcase      : {name_of(links.showcase, 'NOT FOUND')}")
    print(f"  voice rooms   : {', '.join(r.name for r in links.rooms) or 'none'}")

    welcome = server_setup._by_name(guild.text_channels, server_setup.WELCOME_CHANNEL)
    print(f"\n{'-' * 74}\n  {name_of(welcome, '#' + server_setup.WELCOME_CHANNEL + ' (MISSING)')}"
          f"   [picture: {server_setup.WELCOME_IMAGE_NAME}]\n{'-' * 74}")
    for e in server_setup.welcome_embeds(guild, links):
        print(f"  {e.title}\n\n{e.description}\n\n  ({e.footer.text if e.footer else ''})")

    for planned, (title, body) in server_setup.channel_copy(links).items():
        ch = server_setup._copy_target(guild, planned, links)
        if ch is None:
            print(f"\n  [skipped: no channel plays the '{planned}' role on this server]")
            continue
        print(f"\n{'-' * 74}\n  #{ch.name}\n{'-' * 74}\n  {title}\n\n{body}")

    for room in links.rooms:
        e = server_setup.room_embed(room.name, links)
        print(f"\n{'-' * 74}\n  🔊 {room.name}\n{'-' * 74}\n  {e.title}\n\n{e.description}")
    print()


class Refresher(discord.Client):
    async def on_ready(self) -> None:
        try:
            for g in self.guilds:
                print(f"\nserver: {g.name} (id {g.id})")
                if not APPLY:
                    _preview(g)
                    continue
                report = await server_setup.refresh_copy(g, _ids())
                for label, items in (("wrote", report.created), ("left alone", report.skipped),
                                     ("FAILED", report.failed)):
                    if items:
                        print(f"\n  {label} ({len(items)}):")
                        for i in items:
                            print(f"    . {i}")
        finally:
            await self.close()


asyncio.run(Refresher(intents=discord.Intents.default()).start(CFG.token))
