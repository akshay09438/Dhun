"""Hide #the-door from people who are already in.

    python services/discord-bot/scripts/hide_door_from_members.py            # DRY RUN (default)
    python services/discord-bot/scripts/hide_door_from_members.py --apply    # actually do it

THE PROBLEM. `#the-door` is the lobby, and it is visible to `@everyone` on purpose - that is how
a stranger finds it. But `@Member` inherits that visibility, so somebody who is already IN keeps
seeing the lobby they no longer belong in. Founder, 2026-08-14: the first 30 people "should not be
shown the door channel straightaway", they should land on `#read-this-first`.

THE FIX, and it is one rule on one channel: deny `view_channel` to `@Member` on `#the-door`.
Discord resolves an explicit role deny over the `@everyone` allow, so:

  * a stranger (no `@Member`)  -> still sees the lobby, exactly as before;
  * anybody who has been let in -> the lobby disappears and `#read-this-first` is the first thing
    they see.

That covers BOTH sides of the 30 threshold with nothing dynamic and nothing to keep in sync: below
30 the bot grants `@Member` on arrival, so the lobby vanishes a second later; at 30+ no role is
granted, so the lobby stays put and the form is met.

WHY THIS IS SAFE, given the 2026-08-13 incident that half-locked the live server:

  * it touches ONE channel and ONE role, and NEVER `@everyone` - the failure that hurt last time
    was denying `@everyone` before allowing `@Member`, which locked the bot out of the channel it
    was editing. Nothing here can do that;
  * the owner and any Administrator keep seeing everything regardless - Discord's Administrator
    bypasses channel overwrites - so it cannot lock the founder out of their own lobby;
  * `lock_the_door.py` explicitly SKIPS `#the-door` (its `keep_open` set), so re-running that
    script can never silently undo this;
  * it is reversible in one call, and `--undo` does exactly that.

Plain ASCII output only: this machine's console cannot encode anything else, and that has already
cost this project three separate incidents.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import discord  # noqa: E402
import door  # noqa: E402
from botconfig import load_config  # noqa: E402

CFG = load_config()
APPLY = "--apply" in sys.argv
UNDO = "--undo" in sys.argv

WELCOME_CHANNEL = "read-this-first"

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
client = discord.Client(intents=intents)

_exit_code = 0


def say(s=""):
    print(s, flush=True)


def _visible_to(channel, role, everyone) -> bool:
    """Would somebody holding `role` (and nothing else) see this channel?"""
    rv = channel.overwrites_for(role).view_channel
    if rv is not None:
        return rv
    ev = channel.overwrites_for(everyone).view_channel
    return ev is not False


async def run_for(guild):
    global _exit_code
    everyone = guild.default_role
    role = discord.utils.get(guild.roles, name=door.MEMBER_ROLE)
    lobby = guild.get_channel(CFG.door_channel_id) if CFG.door_channel_id else None
    if lobby is None:
        lobby = discord.utils.get(guild.text_channels, name="the-door")

    say("=" * 76)
    say(f"SERVER: {guild.name}")
    say("=" * 76)
    if role is None:
        say(f"  STOP: there is no @{door.MEMBER_ROLE} role on this server. Nothing to do.")
        _exit_code = 2
        return
    if lobby is None:
        say("  STOP: could not find the lobby channel (#the-door). Nothing to do.")
        _exit_code = 2
        return

    current = lobby.overwrites_for(role).view_channel
    wanted = None if UNDO else False
    say(f"  channel                 : #{lobby.name}")
    say(f"  role                    : @{role.name}")
    say(f"  @{role.name} can see it now : "
        f"{'yes' if _visible_to(lobby, role, everyone) else 'no'}  (overwrite={current!r})")
    say(f"  after this change       : "
        f"{'yes (restored)' if UNDO else 'no'}  (overwrite={wanted!r})")
    say("")

    if current == wanted:
        say("  ALREADY IN THE WANTED STATE - nothing to change.")
    else:
        verb = "RESTORE" if UNDO else "HIDE"
        say(f"  WOULD {verb}: set view_channel={wanted!r} for @{role.name} on #{lobby.name}")
        if APPLY:
            if UNDO:
                await lobby.set_permissions(
                    role, overwrite=None, reason="Undo: show the lobby to members again")
            else:
                await lobby.set_permissions(
                    role, view_channel=False,
                    reason="Members are already in; the lobby is for strangers")
            say("  APPLIED.")

    # ---- what it looks like afterwards ------------------------------------------------------
    say("")
    say("-- AFTERWARDS, WHAT EACH PERSON SEES " + "-" * 39)
    effective = wanted if (APPLY or current == wanted) else wanted    # the intended end state

    def as_member(c):
        if c.id == lobby.id:
            return effective is not False
        return _visible_to(c, role, everyone)

    stranger, member = [], []
    for c in guild.channels:
        if isinstance(c, discord.CategoryChannel):
            continue
        if c.overwrites_for(everyone).view_channel is not False:
            stranger.append(c.name)
        if as_member(c):
            member.append(c.name)

    say(f"  A STRANGER (no @{role.name}) sees {len(stranger)}:")
    for n in stranger:
        say(f"      {n}" + ("   <-- the lobby, still findable" if n == lobby.name else ""))
    say(f"  SOMEBODY WHO IS IN (@{role.name}) sees {len(member)}:")
    for n in member:
        mark = ""
        if n == lobby.name:
            mark = "   <-- LOBBY STILL SHOWING (this is what we are fixing)"
        elif n == WELCOME_CHANNEL:
            mark = "   <-- what they should land on"
        say(f"      {n}{mark}")

    if lobby.name in member and not UNDO:
        say("")
        say("  NOTE: the lobby is still listed above because this was a DRY RUN.")

    say("")
    say("  The owner and anyone with Administrator keep seeing every channel regardless -")
    say("  Discord's Administrator permission bypasses channel rules. You will still see")
    say(f"  #{lobby.name} yourself.")


@client.event
async def on_ready():
    try:
        for guild in client.guilds:
            await run_for(guild)
    except Exception:  # noqa: BLE001 - print loudly; a silent exit is the failure mode here
        import traceback
        traceback.print_exc()
        globals()["_exit_code"] = 1
    finally:
        await client.close()


token = os.environ.get("DISCORD_TOKEN", "").strip()
if not token:
    say("no DISCORD_TOKEN in the environment; cannot log in")
    raise SystemExit(2)

client.run(token, log_handler=None)

if not APPLY:
    say("")
    say("=" * 76)
    say("DRY RUN - nothing was changed. Add --apply to do it, or --undo --apply to reverse it.")
    say("=" * 76)
raise SystemExit(_exit_code)
