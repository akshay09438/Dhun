"""📌 Pin it - carrying a grind up into the showcase channel.

The community does the curating: anyone can pin anyone's grind, because the person who made it is
the worst judge of whether it deserves to live. Pinning is recorded in the store so a second press
cannot post a duplicate, which matters because the button stays live for half an hour and people
double-tap.
"""
from __future__ import annotations

import logging
from pathlib import Path

import discord

import recall
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


def _engine():
    """The engine client. Local import: showcase is imported by bot, so this cannot be top-level."""
    import bot as _bot
    return _bot.bot.api


async def pin(ctx, interaction: discord.Interaction) -> str:
    """Repost a finished grind into the showcase. Returns a plain sentence for the presser."""
    if ctx.number is None:
        return "Give it a second, this one is still arriving."

    channel = _channel(interaction)
    if channel is None:
        return ("There is no showcase channel set up yet, so there is nowhere to pin it. "
                "Ask an admin to run `/setup`.")

    # GET IT BACK BEFORE GIVING UP. This used to read `ctx.audio_path` and, finding nothing, answer
    # "still arriving" - to 22 grinds whose audio had been deleted days earlier. The bot's copy
    # lives in Windows Temp and the engine evicts a render after seven days, so an old grind having
    # no local file is normal rather than exceptional. The engine is asked first, and only a mix
    # genuinely past its seven days is refused.
    row = store.get(ctx.number)
    wav = ctx.audio_path if (ctx.audio_path and Path(ctx.audio_path).exists()) else None
    if wav is None:
        wav = await recall.audio_for(row, _engine())
    if wav is None:
        return (f"Grind #{ctx.number} is gone. I keep the audio for seven days and this one is past "
                f"that, so there is nothing left to show — sorry. Run 🔁 **Again** on it and you "
                f"will get a fresh take of the same two songs.")

    # ONLY NOW. `mark_pinned` is one-shot because people double-tap, so burning it on a press that
    # could not find the audio would mean the mix could never be shown even once it is recoverable.
    if not store.mark_pinned(ctx.number, _now()):
        return f"Grind #{ctx.number} is already up in {channel.mention}."

    embed = ui.grind_embed(number=ctx.number, user=ctx.interaction.user,
                           pairs=ctx.named_pairs(), total_secs=ctx.duration)
    embed.set_footer(text=f"pinned by {interaction.user.display_name}")
    try:
        # Re-attach the audio rather than linking back: a link makes people leave the channel,
        # and the showcase is meant to be scrollable and listenable on its own.
        clip = await ctx._attach(wav)
        posted = await channel.send(embed=embed, files=[clip] if clip else [])
        # THE REACTION SIGNAL LIVES HERE NOW (2026-08-15). A grind card is private to its maker, and
        # Discord will not put reactions on a private message, so this public copy is the only place
        # 🔥 💀 😐 can exist. Point the grind's message id at it as well, because the bot finds a
        # grind FROM the message that was reacted to - without this every reaction on a shared mix
        # would be silently discarded. Best-effort: a mix that is up but unreactable is a nuisance,
        # a pin that half-failed after posting would be worse.
        try:
            if posted is not None:
                store.attach_showcase_message(ctx.number, posted.id,
                                              channel_id=getattr(channel, "id", None))
                for emoji in ui.REACTIONS:
                    await posted.add_reaction(emoji)
        except Exception:  # noqa: BLE001
            log.warning("could not set up reactions on the showcase post", exc_info=True)
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
    # The row's own reference as a fallback: a card rebuilt after a restart may carry none, and the
    # grind it belongs to is exactly the old one most in need of protecting from the next sweep.
    ref = ctx.ref_id or (row["ref_id"] if row is not None else None)
    if ref:
        await _engine().keep_render(ref)
    else:
        log.warning("grind #%s pinned with no ref_id — its render cannot be protected", ctx.number)
    return f"Grind #{ctx.number} is up in {channel.mention}."


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
