"""📌 Pin it - carrying a grind up into the showcase channel.

The community does the curating: anyone can pin anyone's grind, because the person who made it is
the worst judge of whether it deserves to live. Pinning is recorded in the store so a second press
cannot post a duplicate, which matters because the button stays live for half an hour and people
double-tap.
"""
from __future__ import annotations

import logging

import discord

import store
import ui
from botconfig import load_config

log = logging.getLogger("promptdj.discord")
CFG = load_config()


def _channel(interaction: discord.Interaction):
    """The showcase channel, or None if it is not configured or not reachable."""
    if not CFG.fresh_grinds_channel_id or interaction.guild is None:
        return None
    return interaction.guild.get_channel(CFG.fresh_grinds_channel_id)


async def pin(ctx, interaction: discord.Interaction) -> str:
    """Repost a finished grind into the showcase. Returns a plain sentence for the presser."""
    if ctx.number is None or ctx.audio_path is None:
        return "Give it a second, this one is still arriving."

    channel = _channel(interaction)
    if channel is None:
        return ("There is no showcase channel set up yet, so there is nowhere to pin it. "
                "Ask an admin to run `/setup`.")

    if not store.mark_pinned(ctx.number, _now()):
        return f"Grind #{ctx.number} is already up in {channel.mention}."

    embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                           pairs=ctx.named_pairs(), total_secs=ctx.duration)
    embed.set_footer(text=f"pinned by {interaction.user.display_name}")
    try:
        # Re-attach the audio rather than linking back: a link makes people leave the channel,
        # and the showcase is meant to be scrollable and listenable on its own.
        clip = await ctx._attach(ctx.audio_path)
        await channel.send(embed=embed, files=[clip] if clip else [])
    except discord.Forbidden:
        store.mark_unpinned(ctx.number)
        return f"I cannot post in {channel.mention}. An admin needs to let me in."
    except Exception as e:  # noqa: BLE001
        store.mark_unpinned(ctx.number)
        log.exception("pin failed")
        return f"Could not pin it: {e}"

    # PINNED = KEEP IT. Founder rule 2026-08-13: the mixes in the best-mixes tab are the ones that
    # must never be removed, and everything else may go. The MP3 above already lives in Discord for
    # good; this protects the local full-quality render from routine tidying, which is also what
    # lets somebody play or re-pin this grind months from now instead of finding it swept.
    # Only AFTER the post succeeded — a pin that failed should leave nothing behind.
    if ctx.ref_id:
        import bot as _bot  # local import: showcase is imported by bot, so this cannot be top-level
        # `_bot.bot` — the module is `bot` and the client instance inside it is ALSO called `bot`.
        await _bot.bot.api.keep_render(ctx.ref_id)
    else:
        log.warning("grind #%s pinned with no ref_id — its render cannot be protected", ctx.number)
    return f"Grind #{ctx.number} is up in {channel.mention}."


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
