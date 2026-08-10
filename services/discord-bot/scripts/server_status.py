"""Print what a Grinder server actually looks like right now. READ-ONLY.

    python services/discord-bot/scripts/server_status.py

Connects with the bot's own credentials (the same gitignored .env `bot.py` reads - the token is
never printed), lists every channel, role, emoji and boost feature, compares that against the
planned STRUCTURE, and exits. Nothing is created, changed or deleted.

Exists because "what's left to set up?" should be answered from the live server rather than from
memory. Two bugs this session came from assuming the server matched the plan when it didn't.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                     # noqa: E402

import server_setup                                # noqa: E402
from botconfig import load_config                  # noqa: E402

CFG = load_config()


class Inspector(discord.Client):
    async def on_ready(self) -> None:
        try:
            for g in self.guilds:
                self._report(g)
        finally:
            await self.close()

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


def main() -> int:
    client = Inspector(intents=discord.Intents.default())
    try:
        client.run(CFG.token, log_handler=None)
    except discord.LoginFailure:
        print("Login failed - check the token in services/discord-bot/.env")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
