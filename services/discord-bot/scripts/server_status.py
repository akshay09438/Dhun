"""Print what a Grinder server actually looks like right now. READ-ONLY.

    python services/discord-bot/scripts/server_status.py

Connects with the bot's own credentials (the same gitignored .env `bot.py` reads - the token is
never printed), lists every channel, role, emoji and boost feature, reports who can do anything
they like on the server, compares all of it against the plan, and exits. Nothing is created,
changed or deleted.

Exists because "what's left to set up?" should be answered from the live server rather than from
memory. Two bugs this session came from assuming the server matched the plan when it didn't - and
the SECURITY section exists for the same reason: the handoff recorded "the bot appears to still
hold Administrator" as a CLAIM, and a claim about permissions is worth exactly nothing next to a
reading taken off the live server.
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

# The founder's machine is Windows, where the console defaults to a codepage that cannot print
# anything outside Latin-1. One tick mark was enough to kill this report silently. Ask for UTF-8
# and carry on if the stream does not support it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    except Exception:                                # noqa: BLE001 - best effort, never fatal
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                     # noqa: E402

import door                                        # noqa: E402
import server_setup                                # noqa: E402
from botconfig import load_config                  # noqa: E402

CFG = load_config()

# ─────────────────────────────────────────────────────────────────────────────
# What Grinder actually needs
#
# Every entry below is traced to the line of code that calls it - this list is not a guess, and
# it is the whole argument for taking Administrator away. Administrator is a single switch that
# grants all of these AND every destructive power the bot has no code to use: it cannot kick, it
# cannot ban, it cannot time anybody out, it cannot delete a channel. Grep the bot for `.kick(`,
# `.ban(` or `delete(` outside the tests and you get nothing.
#
# Keep this list honest. If a new feature calls an API that needs a permission, add it here in the
# same change - the security check is only as good as this table.
CORE_PERMS: tuple[tuple[str, str], ...] = (
    ("view_channel",         "see the channels it works in"),
    ("send_messages",        "post a grind card at all"),
    ("embed_links",          "the cards themselves are embeds"),
    ("attach_files",         "send the finished mix as a playable file"),
    ("read_message_history", "find its own earlier posts to edit in place"),
    ("add_reactions",        "put the starting fire/skull/shrug reactions on a grind"),
    ("manage_messages",      "pin its own posts (booth.py, server_setup.py)"),
    ("create_instant_invite", "/invitefriend's one-use link (door.py)"),
    ("manage_roles",         "hand out @Member, and set channel permissions"),
    ("connect",              "join a listening room"),
    ("speak",                "play a mix out loud"),
)

# Only used by /setup, which builds a server once. Missing these is not an outage - it means a
# future /setup would half-fail, and /setup must never be run on the founder's live server anyway.
SETUP_PERMS: tuple[tuple[str, str], ...] = (
    ("manage_channels",           "/setup creates the categories and channels"),
    ("manage_guild",              "/setup sets the server icon"),
    ("manage_emojis_and_stickers", "/setup uploads the six custom emojis"),
)

# Nothing in the bot calls anything that needs these. Holding one is not an active bug; it is
# standing blast radius - the damage available to whoever gets hold of the token.
#
# Deliberately NOT listed here: `manage_expressions`, which is discord.py's alias for the same
# permission bit as `manage_emojis_and_stickers` in SETUP_PERMS. Listing both would report the one
# permission as needed and over-granted at the same time.
NEVER_NEEDED: tuple[str, ...] = (
    "administrator", "kick_members", "ban_members", "moderate_members",
    "manage_webhooks", "mention_everyone", "view_audit_log", "manage_nicknames",
    "manage_threads", "manage_events",
)


def audit_permissions(perms: object) -> dict[str, list[str]]:
    """Compare what the bot HOLDS against what it PROVABLY uses. Pure - takes anything with
    permission attributes, so the tests can hand it a plain stub.

    Administrator is deliberately NOT treated as "has everything". Discord grants every power
    through it, so scoring it as satisfying each need would report a perfect green board and hide
    the exact thing this check was written to find. It is reported as a finding of its own, and
    the real per-permission boxes are read as they actually are underneath it.
    """
    def held(name: str) -> bool:
        return bool(getattr(perms, name, False))

    return {
        "missing_core": [n for n, _ in CORE_PERMS if not held(n)],
        "missing_setup": [n for n, _ in SETUP_PERMS if not held(n)],
        "over_granted": [n for n in NEVER_NEEDED if held(n)],
    }


def admin_roles(guild: object) -> list:
    """Every role on the server that carries Administrator - i.e. every role that can do anything
    at all, including deleting channels and banning people. Pure.

    Returns the role OBJECTS, not their names. The live server has two different roles both called
    "Grinder", so looking a name back up to count its members can silently answer about the wrong
    one - in a report whose entire job is to say who holds dangerous power."""
    return [r for r in getattr(guild, "roles", [])
            if getattr(getattr(r, "permissions", None), "administrator", False)]


def reason_for(name: str) -> str:
    for n, why in CORE_PERMS + SETUP_PERMS:
        if n == name:
            return why
    return ""


def ticked_permissions(me: object) -> discord.Permissions:
    """What is ACTUALLY ticked on the bot's roles, ignoring the Administrator shortcut.

    This exists because `Member.guild_permissions` is a lie for this purpose - and a dangerous
    one. Discord defines Administrator as granting everything, so discord.py short-circuits and
    returns `Permissions.all()` for anybody who holds it. Audit that and the report says "has
    everything it needs", the founder unticks Administrator on the strength of it, and the bot
    silently loses Manage Roles: approvals then record as approved while the person still sees
    nothing - the precise silent failure already in the handoff as an unexplained incident.

    So read the union of the raw permission bits on the bot's own roles instead. That is what
    would survive Administrator being switched off.
    """
    value = 0
    for role in getattr(me, "roles", []):
        value |= getattr(getattr(role, "permissions", None), "value", 0)
    return discord.Permissions(value)


class Inspector(discord.Client):
    #: set when the report could not be completed, so main() can exit non-zero instead of
    #: letting a truncated report pass for a clean one.
    _failed = False

    async def on_ready(self) -> None:
        # discord.py routes an exception raised in an event handler to its own logger, and we start
        # the client with `log_handler=None`, so that logger has nowhere to write: the traceback is
        # discarded and the script simply STOPS MID-REPORT with no error and exit code 0. That is
        # how a single un-printable character truncated this report the first time it was run for
        # real. A check that can go quiet on failure is the thing it was written to prevent, so
        # catch and print here rather than trusting the event loop to tell anybody.
        try:
            await self._report_app()
            for g in self.guilds:
                self._report(g)
                self._report_security(g)
        except Exception:                            # noqa: BLE001 - report ANY failure, loudly
            print("\n!! THE CHECK ITSELF FAILED - the report above is INCOMPLETE. "
                  "Do not read it as a clean result.\n")
            traceback.print_exc()
            self._failed = True
        finally:
            await self.close()

    async def _report_app(self) -> None:
        """The bot's two pictures, which are DIFFERENT settings and get confused constantly:

        * the bot USER avatar - what shows beside its messages. Set by the API, so /setup does it.
        * the APPLICATION icon - what shows in Discord's slash-command picker. Developer Portal
          only; no bot can change its own. This is why the old "G" lingered next to /mix long after
          the avatar was replaced.
        """
        user = self.user
        print(f"\n{'=' * 72}\nGrinder app\n{'=' * 72}")
        print(f"  bot avatar (beside messages) : {user.display_avatar.url if user else '?'}")
        try:
            info = await self.application_info()
            if info.icon is None:
                print("  app icon (command picker)    : NOT SET -> Discord shows a default")
            else:
                print(f"  app icon (command picker)    : {info.icon.url}")
        except Exception as e:  # noqa: BLE001 - a read-only check must never be the thing that fails
            print(f"  app icon (command picker)    : couldn't read ({e})")

    def _report(self, g: discord.Guild) -> None:
        planned_names = {c.label.lower() for cat in server_setup.STRUCTURE for c in cat.channels}
        planned_cats = {cat.name.lower() for cat in server_setup.STRUCTURE}

        print(f"\n{'=' * 72}\n{g.name}  (id {g.id})   members: {g.member_count}\n{'=' * 72}")
        print(f"  icon set : {g.icon is not None}")
        print(f"  boost    : level {g.premium_tier}, {g.premium_subscription_count or 0} boosts")
        for feat, need in (("BANNER", "banner (needs level 2)"),
                           ("INVITE_SPLASH", "invite splash (needs level 1)")):
            print(f"  {need:28s} {'AVAILABLE' if feat in g.features else 'locked'}")

        print("\n  CHANNELS")
        for cat in [None] + sorted(g.categories, key=lambda c: c.position):
            kids = ([c for c in g.channels
                     if not isinstance(c, discord.CategoryChannel) and c.category is None]
                    if cat is None else list(cat.channels))
            if cat is None and not kids:
                continue
            if cat is not None:
                mark = "" if cat.name.lower() in planned_cats else "   <- not in the plan"
                print(f"    [{cat.name}]{mark}" + ("   <- EMPTY" if not kids else ""))
            else:
                print("    (no category)")
            for c in kids:
                kind = "voice" if isinstance(c, discord.VoiceChannel) else "text "
                extra = "" if c.name.lower() in planned_names else "   <- not in the plan"
                print(f"       {kind} #{c.name}{extra}")

        missing = [c.label for cat in server_setup.STRUCTURE for c in cat.channels
                   if c.label.lower() not in {ch.name.lower() for ch in g.channels}]
        print(f"\n  missing from the plan: {missing or 'nothing'}")

        print("\n  ROLES (excluding @everyone)")
        for r in sorted(g.roles, key=lambda r: -r.position):
            if r.name != "@everyone":
                who = f"{len(r.members)} member(s)"
                print(f"    @{r.name:<16} {who}{'   <- bot role' if r.managed else ''}")

        have = {e.name for e in g.emojis}
        want = {n for n, _ in server_setup.brand.emoji_files()}
        print(f"\n  EMOJIS: {len(have)} uploaded; missing: {sorted(want - have) or 'none'}")

    def _report_security(self, g: discord.Guild) -> None:
        """Who can do anything here, and is Grinder carrying more power than it uses.

        Read-only, and written to be read by somebody who does not code: every finding says what
        it means and what to do, not just which flag is set.
        """
        print("\n  SECURITY")

        owner = getattr(g, "owner", None)
        print(f"    server owner            : {owner or 'unknown'} "
              f"(only the owner can delete or hand over the server)")

        # Discord gates a set of permissions behind the server's MFA level, and `manage_roles` -
        # the one the Door needs to hand out @Member - is on that list. So switching this on while
        # the OWNER's account has no 2FA does not merely fail to help: it stops the bot granting
        # roles. Approvals would record as approved and the person would still see nothing, which
        # is the exact silent failure this project has already chased once. Say so here rather than
        # leaving it in somebody's memory.
        mfa = getattr(g, "mfa_level", None)
        if mfa is discord.MFALevel.require_2fa:
            print("    2FA for admin actions   : REQUIRED  OK")
            print("       reminder: this gates Manage Roles. If the owner's 2FA is ever removed,")
            print("       the Door stops granting @Member - silently. Re-run this check first.")
        elif mfa is discord.MFALevel.disabled:
            print("    2FA for admin actions   : not required")
            print("       Deliberate for now (2026-08-13): worth little at this size, and it is a")
            print("       TRAP if switched on carelessly - it gates Manage Roles, so with no 2FA")
            print("       on the OWNER's account the Door stops granting @Member without saying")
            print("       so. If you ever turn it on: owner 2FA first, then re-run this check.")
        else:
            print(f"    2FA for admin actions   : couldn't read ({mfa})")

        carriers = admin_roles(g)
        print("\n    roles that can do ANYTHING (Administrator):")
        if not carriers:
            print("       none - only the owner, which cannot be removed. This is the goal state.")
        for role in carriers:
            who = f"{len(role.members)} member(s)"
            note = "  <- the bot; see below" if role.managed else ""
            print(f"       @{role.name:<20} {who}{note}")

        me = getattr(g, "me", None)
        if me is None:
            print("\n    Grinder's own powers    : not in this server")
            return

        # NOT me.guild_permissions - see ticked_permissions(). While Administrator is on, Discord
        # reports every permission as held, which would make this whole section read clean.
        perms = ticked_permissions(me)
        audit = audit_permissions(perms)
        print("\n    Grinder's own powers  (what is really ticked, ignoring Administrator):")
        if audit["over_granted"]:
            worst = "administrator" in audit["over_granted"]
            print(f"       holds but never uses  : {', '.join(audit['over_granted'])}")
            if worst:
                print("          ^ ADMINISTRATOR. Nothing in the bot's code needs it - it cannot "
                      "kick,\n            ban, time out or delete anything, because none of that "
                      "is written.\n            Anyone who steals the token inherits all of it.")
        else:
            print("       holds but never uses  : nothing  OK")

        if audit["missing_core"]:
            print("       WOULD BE MISSING if Administrator were switched off today:")
            for n in audit["missing_core"]:
                print(f"          {n:<24} ({reason_for(n)})")
            print("          ^ tick these FIRST, then untick Administrator. Doing it the other "
                  "way\n            round breaks the bot between the two clicks.")
        else:
            print("       everything it needs   : ticked in its own right  OK")

        if audit["missing_setup"]:
            print(f"       missing, /setup only  : {', '.join(audit['missing_setup'])}"
                  "  (harmless - never run /setup on this server)")

        # can_grant_member reads the LIVE effective permissions, so it answers "does approval work
        # right now". Pair it with the ticked reading to answer "will it still work afterwards".
        ok, why = door.can_grant_member(g)
        would_keep_roles = "manage_roles" not in audit["missing_core"]
        above = getattr(getattr(me, "top_role", None), "position", 0)
        member_role = discord.utils.get(g.roles, name=door.MEMBER_ROLE)
        outranks = member_role is not None and above > member_role.position

        if ok and me.guild_permissions.administrator:
            print("       can it grant @Member? : yes TODAY - but only because of Administrator.")
            print(f"          after Administrator is removed it would be: "
                  f"{'YES' if (would_keep_roles and outranks) else 'NO'}")
            if not would_keep_roles:
                print("             - it has no Manage Roles of its own. Tick that first.")
            if not outranks:
                print(f"             - its role does not sit above @{door.MEMBER_ROLE} in "
                      "Server Settings > Roles.\n               Drag it above, or approvals fail "
                      "silently: recorded as approved,\n               person still sees nothing.")
        elif ok:
            print("       can it grant @Member? : yes, on its own merits  OK")
        else:
            print(f"       can it grant @Member? : NO - {why}")


def main() -> int:
    # The Server Members intent is asked for so role membership counts are REAL. Without it
    # `role.members` is whatever happens to be cached, which for a security report is worse than
    # useless - it under-reports how many people hold Administrator. If the intent is switched
    # off in the Developer Portal we fall back rather than fail, and say which numbers to distrust.
    intents = discord.Intents.default()
    intents.members = True
    client = Inspector(intents=intents)
    try:
        client.run(CFG.token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        print("note: the Server Members intent is off, so role member COUNTS below may read low.")
        print("      Turn it on at Developer Portal > your app > Bot > Server Members Intent.\n")
        client = Inspector(intents=discord.Intents.default())
        try:
            client.run(CFG.token, log_handler=None)
        except discord.LoginFailure:
            print("Login failed - check the token in services/discord-bot/.env")
            return 1
    except discord.LoginFailure:
        print("Login failed - check the token in services/discord-bot/.env")
        return 1
    return 1 if client._failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
