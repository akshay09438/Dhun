"""Delete named channels from the live server.

    python services/discord-bot/scripts/delete_channels.py            # DRY RUN (default)
    python services/discord-bot/scripts/delete_channels.py --apply    # actually delete

IRREVERSIBLE: deleting a channel takes its whole message history with it. So this prints what is
in each one FIRST - author and message count - and refuses to touch anything it was not explicitly
named. Founder, 2026-08-14: "Let's keep it simple" - #announcements, #rules and #fred-again-brag
were never used (Grinder's own placeholder line and nothing else) and are being removed rather than
left as empty rooms a newcomer has to scroll past.

`#read-this-first` STAYS. It is the first thing a new arrival sees.

Matching is by EXACT name. Everything else this evening used substring matching and it bit twice
("Water" also matches "WATERmelon Sugar"); on an operation that destroys history, a near-match is
not acceptable. A name that matches nothing is reported, never guessed at.
"""

import asyncio
import sys
from pathlib import Path

_BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import botconfig  # noqa: E402

CFG = botconfig.load_config()

import discord  # noqa: E402

APPLY = "--apply" in sys.argv
TARGETS = ["announcements", "rules", "fred-again-brag"]
NEVER = {"read-this-first", "the-door", "applications", "get-shit-done", "best-mixes", "general"}

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)


def say(s=""):
    print(s, flush=True)


@client.event
async def on_ready():
    try:
        g = client.guilds[0]
        say(f"=== {g.name} ===")
        say(f"  {'DELETING' if APPLY else 'DRY RUN - would delete'}: {', '.join(TARGETS)}")
        say()
        for name in TARGETS:
            if name in NEVER:                       # belt and braces against a bad edit above
                say(f"  REFUSED  #{name} is on the never-delete list")
                continue
            ch = discord.utils.get(g.text_channels, name=name)
            if ch is None:
                say(f"  SKIP     #{name}: no channel with that exact name")
                continue
            msgs = [m async for m in ch.history(limit=200)]
            authors = {}
            for m in msgs:
                authors[m.author.name] = authors.get(m.author.name, 0) + 1
            say(f"  DELETE   #{name:<18} {len(msgs)} message(s)  {authors or '(empty)'}")
            if APPLY:
                try:
                    await ch.delete(reason="Founder 2026-08-14: unused channels removed")
                    say(f"           deleted")
                except discord.Forbidden:
                    say(f"           REFUSED: Grinder lacks Manage Channels here")
                except discord.HTTPException as e:
                    say(f"           FAILED: {e}")

        say()
        say("  --- channels remaining ---")
        for cat, chans in g.by_category():
            names = [f"#{c.name}" for c in chans]
            if names:
                say(f"    [{cat.name if cat else 'no category'}]  {', '.join(names)}")
        if not APPLY:
            say()
            say("DRY RUN - nothing deleted. Add --apply to do it.")
    finally:
        await client.close()


if not CFG.token:
    say("no bot token configured")
    raise SystemExit(1)
asyncio.run(client.start(CFG.token))
