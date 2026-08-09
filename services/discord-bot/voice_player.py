"""Optional voice playback — the bot joins the caller's voice channel and streams the mix,
like a classic music bot (Rhythm/Groovy).

Voice needs the PyNaCl package (plus ffmpeg, already required). PyNaCl can be awkward to
build on some Windows/ARM setups, so voice degrades GRACEFULLY: if it isn't available, the
clip-in-channel experience (the reliable core) is completely unaffected, and the button just
explains that voice is off on this machine.
"""
from __future__ import annotations

import discord


def voice_supported() -> bool:
    """True only if PyNaCl imported — discord.py needs it to encrypt the voice stream."""
    try:
        import nacl  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — any import/build failure means voice is off
        return False


async def play_in_channel(interaction: "discord.Interaction", audio_path) -> str:
    """Join the presser's voice channel and stream `audio_path`. Returns a plain-language
    status line to show them (ephemerally). Never raises — a demo must not crash on voice."""
    voice_state = getattr(interaction.user, "voice", None)
    if voice_state is None or voice_state.channel is None:
        return "Join a voice channel first, then tap **Play in voice** again."
    if not voice_supported():
        return ("Voice playback isn't available on this machine yet (the PyNaCl package didn't "
                "load). The clip above still plays anywhere — that's the reliable path.")
    channel = voice_state.channel
    guild = interaction.guild
    if guild is None:
        return "Voice playback only works inside a server."
    try:
        vc = guild.voice_client
        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)
        if vc.is_playing():
            vc.stop()
        vc.play(discord.FFmpegPCMAudio(str(audio_path)))
    except Exception as e:  # noqa: BLE001 — surface the reason, never crash
        return f"Couldn't play in voice: {e}"
    return f"▶️ Playing in **{channel.name}**. Tap **Leave voice** to stop."


async def leave(interaction: "discord.Interaction") -> str:
    guild = interaction.guild
    vc = guild.voice_client if guild else None
    if vc is None:
        return "I'm not in a voice channel."
    try:
        await vc.disconnect(force=True)
    except Exception as e:  # noqa: BLE001
        return f"Couldn't leave: {e}"
    return "Left the voice channel."
