"""Close the door on a live Grinder server, safely.

⚠️ THIS IS THE DANGEROUS HALF OF THE FEATURE. It changes permissions on a real server the founder
has hand-tuned and said "never change it from this now". So:

  * It NEVER runs `/setup`, and never creates, renames, deletes or reorders anything the founder
    has set. It touches exactly three things: an `@Member` role, a `#the-door` channel, an
    `#applications` channel - and `@everyone`'s read access.
  * It is a DRY RUN by default. It prints what it would do and changes nothing until `--apply`.
  * It is re-runnable. Everything it makes, it makes only if absent.

THE ORDER IS THE WHOLE SAFETY STORY, and it is not negotiable:

    1. create @Member
    2. GIVE @Member TO EVERY HUMAN ALREADY IN THE SERVER
    3. only then take read access away from @everyone

Reversed, every existing member - including the founder - loses sight of the server for as long as
step 2 takes, and if the script dies in between, permanently. Grant first, restrict second.

The founder's own account keeps administrator permissions throughout, which sit above channel
overwrites, so they cannot lock themselves out even if this script fails halfway.

Usage:
    python scripts/lock_the_door.py            # dry run: says what it would do
    python scripts/lock_the_door.py --apply    # does it, after a typed confirmation
    python scripts/lock_the_door.py --open     # dry run of REOPENING (undo)
    python scripts/lock_the_door.py --open --apply
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import discord

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import door  # noqa: E402
from botconfig import load_config  # noqa: E402

CFG = load_config()

DOOR_CHANNEL = "the-door"
APPLICATIONS_CHANNEL = "applications"
DOOR_TOPIC = "Ask to join. Five short questions."
APPLICATIONS_TOPIC = "Applications land here. Private."


class _Locker(discord.Client):
    def __init__(self, *, apply: bool, reopen: bool) -> None:
        super().__init__(intents=discord.Intents(guilds=True, members=True))
        self.apply = apply
        self.reopen = reopen
        self.plan: list[str] = []

    def _say(self, line: str) -> None:
        self.plan.append(line)
        print(("  DO   " if self.apply else "  would") + "  " + line)

    async def on_ready(self) -> None:
        try:
            await self._run()
        finally:
            await self.close()

    async def _run(self) -> None:
        guild = self.get_guild(CFG.guild_id) if CFG.guild_id else (self.guilds[0] if self.guilds
                                                                   else None)
        if guild is None:
            print("No server found. Set DISCORD_GUILD_ID.")
            return
        print(f"\nServer: {guild.name} ({guild.id})")
        print(f"Mode:   {'REOPEN' if self.reopen else 'CLOSE'} the door "
              f"({'APPLYING' if self.apply else 'dry run'})\n")

        if self.reopen:
            await self._reopen(guild)
        else:
            await self._close(guild)

        if not self.apply:
            print(f"\n{len(self.plan)} change(s) would be made. Nothing was touched.")
            print("Re-run with --apply to do it.")
        else:
            print(f"\nDone. {len(self.plan)} change(s) made.")
            print("\nPut these in your .env so the bot can find the new rooms:")
            for name, ch in (("GRINDER_DOOR_CHANNEL_ID", self._door),
                             ("GRINDER_APPLICATIONS_CHANNEL_ID", self._apps)):
                if ch is not None:
                    print(f"  {name}={ch.id}")

    _door = None
    _apps = None

    async def _close(self, guild: discord.Guild) -> None:
        # ---- 1. the role -------------------------------------------------------------------
        role = discord.utils.get(guild.roles, name=door.MEMBER_ROLE)
        if role is None:
            self._say(f"create role @{door.MEMBER_ROLE}")
            if self.apply:
                role = await guild.create_role(name=door.MEMBER_ROLE,
                                               reason="The door: membership role")
        else:
            print(f"  ok     role @{door.MEMBER_ROLE} already exists")

        # ---- 2. GRANT IT TO EVERYONE ALREADY HERE, BEFORE ANYTHING IS RESTRICTED ------------
        # If this half fails, the server is still exactly as it was - nothing has been taken away
        # yet. That is the entire reason it runs first.
        humans = [m for m in guild.members if not m.bot]
        missing = [m for m in humans if role is None or role not in m.roles]
        self._say(f"give @{door.MEMBER_ROLE} to {len(missing)} existing member(s) "
                  f"(of {len(humans)} humans)")
        if self.apply and role is not None:
            for m in missing:
                try:
                    await m.add_roles(role, reason="The door: keeping existing members in")
                except discord.HTTPException as e:
                    print(f"  WARN   could not give @{door.MEMBER_ROLE} to {m}: {e}")

        # ---- 3. the two new channels -------------------------------------------------------
        self._door = discord.utils.get(guild.text_channels, name=DOOR_CHANNEL)
        if self._door is None:
            self._say(f"create #{DOOR_CHANNEL} (visible to everyone, read only)")
            if self.apply:
                self._door = await guild.create_text_channel(
                    DOOR_CHANNEL, topic=DOOR_TOPIC,
                    overwrites={
                        guild.default_role: discord.PermissionOverwrite(
                            view_channel=True, read_message_history=True, send_messages=False),
                    },
                    reason="The door: the lobby")
        else:
            print(f"  ok     #{DOOR_CHANNEL} already exists")

        self._apps = discord.utils.get(guild.text_channels, name=APPLICATIONS_CHANNEL)
        if self._apps is None:
            self._say(f"create #{APPLICATIONS_CHANNEL} (private, admins only)")
            if self.apply:
                self._apps = await guild.create_text_channel(
                    APPLICATIONS_CHANNEL, topic=APPLICATIONS_TOPIC,
                    overwrites={guild.default_role: discord.PermissionOverwrite(
                        view_channel=False)},
                    reason="The door: where applications are read")
        else:
            print(f"  ok     #{APPLICATIONS_CHANNEL} already exists")

        # ---- 4. ONLY NOW: close every other channel to @everyone ----------------------------
        # NEVER TOUCHED by the members-only pass, for opposite reasons:
        #   #the-door       - must stay visible to everyone, it is the lobby;
        #   #applications   - must stay ADMIN ONLY. It is closed to @everyone already, and the
        #                     self-healing check below would otherwise read "closed but @Member not
        #                     allowed" as damage and helpfully grant every member read access to
        #                     other people's applications. Caught by a dry run, 2026-08-13.
        keep_open = {getattr(self._door, "id", None), getattr(self._apps, "id", None)}

        def needs_work(c) -> bool:
            """A channel needs attention if it is still open to @everyone, OR if it is closed but
            @Member was never allowed in.

            The second half is not hypothetical: it is the state the founder's live server was left
            in on 2026-08-13 when the deny succeeded and the grant did not. A script that only
            looked for "still open" skipped exactly the channels that were broken, which made it
            useless for the one job that mattered - putting it right."""
            if c.id in keep_open:
                return False
            closed = c.overwrites_for(guild.default_role).view_channel is False
            granted = role is not None and c.overwrites_for(role).view_channel is True
            return (not closed) or (not granted)

        to_close = [c for c in guild.channels if needs_work(c)]
        self._say(f"hide {len(to_close)} channel(s) from @everyone, and let @{door.MEMBER_ROLE} "
                  f"see them")
        for c in to_close:
            print(f"           - {c.name}")
        if self.apply and role is not None:
            for c in to_close:
                # GRANT BEFORE DENY, PER CHANNEL. Learned the hard way on the founder's live server
                # 2026-08-13: denying @everyone FIRST locked the BOT out of the same channel in the
                # same instant - its only roles are @Grinder and @everyone, so an @everyone deny is
                # a deny for the bot too. The allow-@Member call then failed with 50001 and the
                # server was left half-locked, with real members seeing nothing and the bot unable
                # to finish OR undo. Only an Administrator toggle by hand got it back.
                #
                # The grant-first rule was already applied one level up (give people the role
                # before restricting anything). This is the same rule at the CHANNEL level, which
                # is where it was missing.
                try:
                    await c.set_permissions(role, view_channel=True,
                                            reason="The door: members keep access")
                except discord.HTTPException as e:
                    print(f"  WARN   could not grant @{door.MEMBER_ROLE} on {c.name}: {e}")
                    print(f"         SKIPPING {c.name} - it stays open rather than risking a "
                          f"channel nobody but an admin can see")
                    continue
                # And the bot's OWN role, so it never loses the ability to undo what it just did.
                try:
                    await c.set_permissions(guild.me.top_role, view_channel=True,
                                            reason="The door: keep the bot able to undo this")
                except discord.HTTPException as e:
                    print(f"  WARN   could not keep the bot's own access on {c.name}: {e}")
                    print(f"         SKIPPING {c.name} - closing it would strand the bot")
                    continue
                try:
                    await c.set_permissions(guild.default_role, view_channel=False,
                                            reason="The door: members only")
                except discord.HTTPException as e:
                    print(f"  WARN   could not close {c.name}: {e}")

        # ---- 5. the lobby post -------------------------------------------------------------
        if self._door is not None:
            self._say(f"post the lobby message in #{DOOR_CHANNEL}")
            if self.apply:
                existing = [m async for m in self._door.history(limit=20)
                            if m.author.id == self.user.id]
                if existing:
                    await existing[-1].edit(embed=door.lobby_embed(), view=door.DoorView())
                else:
                    await self._door.send(embed=door.lobby_embed(), view=door.DoorView())

    async def _reopen(self, guild: discord.Guild) -> None:
        """The undo. Give @everyone back sight of everything this script hid."""
        hidden = [c for c in guild.channels
                  if c.overwrites_for(guild.default_role).view_channel is False
                  and c.name != APPLICATIONS_CHANNEL]
        self._say(f"show {len(hidden)} channel(s) to @everyone again")
        for c in hidden:
            print(f"           - {c.name}")
        if self.apply:
            for c in hidden:
                try:
                    await c.set_permissions(guild.default_role, overwrite=None,
                                            reason="The door: reopened")
                except discord.HTTPException as e:
                    print(f"  WARN   could not reopen {c.name}: {e}")
        print(f"\n  note   #{APPLICATIONS_CHANNEL} stays private, and @{door.MEMBER_ROLE} is left "
              "in place - neither does any harm open.")


def main() -> int:
    apply = "--apply" in sys.argv
    reopen = "--open" in sys.argv
    token = CFG.token or os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        print("No bot token. Set DISCORD_BOT_TOKEN in services/discord-bot/.env")
        return 2

    if apply:
        what = "REOPEN the server to everyone" if reopen else "CLOSE the server behind the door"
        print(f"\nThis will {what}.")
        print("Existing members are given @Member FIRST, so nobody already inside loses access.")
        if input('Type "yes" to go ahead: ').strip().lower() != "yes":
            print("Nothing was changed.")
            return 1

    client = _Locker(apply=apply, reopen=reopen)
    try:
        client.run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        print("\nThis script needs the SERVER MEMBERS intent to see who is already in the server.")
        print("Turn it on: Discord Developer Portal > your app > Bot > Server Members Intent.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
