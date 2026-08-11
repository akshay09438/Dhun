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
    """True only if BOTH voice libraries imported.

    `davey` joined `nacl` here on 2026-08-12. discord.py 2.7 requires davey unconditionally for
    any voice at all — `VoiceClient.__init__` raises before a single packet is sent — so checking
    only PyNaCl made this function answer "yes, voice works" on a machine where it certainly does
    not, and the failure then surfaced as a raw RuntimeError halfway through a grind instead of as
    the plain sentence this gate exists to produce.

    davey publishes no ARM-Windows build, so on the ARM environment this is correctly False; the
    Intel environment (`.venv-x64`, which Start-Grinder.bat prefers) has it and this is True."""
    try:
        import nacl  # noqa: F401
        import davey  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — any import/build failure means voice is off
        return False


def voice_unavailable_reason() -> str | None:
    """WHY voice is off, in words a person can act on, or None when it works. A gate that only
    says "no" sends someone hunting; this one names the missing piece and the fix."""
    try:
        import nacl  # noqa: F401
    except Exception:  # noqa: BLE001
        return "the PyNaCl package did not load"
    try:
        import davey  # noqa: F401
    except Exception:  # noqa: BLE001
        return ("the davey package is missing - it has no ARM build, so Grinder must run on the "
                "Intel environment (.venv-x64), which Start-Grinder.bat prefers automatically")
    return None


async def play_in_channel(interaction: "discord.Interaction", audio_path) -> str:
    """Join the presser's voice channel and stream `audio_path`. Returns a plain-language
    status line to show them (ephemerally). Never raises — a demo must not crash on voice."""
    voice_state = getattr(interaction.user, "voice", None)
    if voice_state is None or voice_state.channel is None:
        return "Join a voice channel first, then tap **Play in voice** again."
    if not voice_supported():
        return (f"Voice playback isn't available on this machine yet ({voice_unavailable_reason()}). "
                "The clip above still plays anywhere — that's the reliable path.")
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


async def play_in(channel, audio_path, *, on_finished=None) -> None:
    """Play into ONE named channel, and call `on_finished` when the audio ends.

    Different from `play_in_channel` above in the two ways that matter for The Booth: it targets a
    fixed room rather than following whoever pressed a button, and it tells the caller when the
    track finishes so the next one can start. Without that callback the room would go quiet after
    one grind and stay quiet with the bot still sitting in it.
    """
    import asyncio

    if not voice_supported():
        raise RuntimeError(f"voice playback is unavailable ({voice_unavailable_reason()})")

    guild = channel.guild
    vc = guild.voice_client
    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)
    if vc.is_playing():
        vc.stop()

    loop = asyncio.get_running_loop()

    def _after(err: Exception | None) -> None:
        # discord.py calls this from a worker thread, so hop back onto the event loop before
        # touching anything async. Doing the work here directly would be a race.
        if on_finished is not None:
            asyncio.run_coroutine_threadsafe(on_finished(), loop)

    vc.play(discord.FFmpegPCMAudio(str(audio_path)), after=_after)


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
