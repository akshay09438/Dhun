"""Grinder's visual identity — Rythm-style cards in the app's Electric Violet.

Pure builders (no network, no Discord state) so they're unit-testable. Every user-facing message
routes through here, so the look is consistent and the colour lives in ONE place. Modelled on the
Rythm music bot's now-playing card (title + progress bar + fields + requester), because Discord
users already know that shape — but Grinder mixes two catalog songs; it never searches/plays
arbitrary tracks.
"""
from __future__ import annotations

import wave
from pathlib import Path

import discord

# The app's "Electric Violet" accent (#6d3bf5) — identical to the web app + the marker tool.
ACCENT = 0x6D3BF5
FAIL = 0xB00020
BOT_NAME = "Grinder"

# progress-bar glyphs (Rythm-style slider)
_FILL, _KNOB, _EMPTY = "━", "🔘", "─"


def mmss(seconds: float | int | None) -> str:
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


def bar(elapsed: float, total: float, width: int = 18) -> str:
    """A Rythm-style slider: `━━━━🔘──────  0:12 / 3:45`. At elapsed 0 the knob sits at the start."""
    total = max(float(total or 0), 0.0)
    elapsed = min(max(float(elapsed or 0), 0.0), total) if total else 0.0
    pos = int((elapsed / total) * (width - 1)) if total else 0
    track = _FILL * pos + _KNOB + _EMPTY * (width - 1 - pos)
    return f"{track}  `{mmss(elapsed)} / {mmss(total)}`"


def wav_duration(path: str | Path) -> float:
    """Duration of a WAV via the stdlib (no extra dep). 0.0 if unreadable."""
    try:
        with wave.open(str(path), "rb") as w:
            fr = w.getframerate()
            return w.getnframes() / fr if fr else 0.0
    except Exception:  # noqa: BLE001 — a duration read must never break a message
        return 0.0


def _requester(user: discord.abc.User | None) -> str:
    return f"Requested by {getattr(user, 'display_name', None) or getattr(user, 'name', 'you')}"


def cooking_embed(beat: str, vocals: str, take: int, max_takes: int) -> discord.Embed:
    e = discord.Embed(
        title="Cooking your mix…",
        description=(f"🎧  **{beat}**  ·  the beat\n"
                     f"🎤  **{vocals}**  ·  the vocals\n\n"
                     f"`▚▚▚▚▚▚▚▚▚▚`  blending on the beat…"),
        color=ACCENT)
    e.set_author(name=f"{BOT_NAME} · mixing")
    e.set_footer(text=f"Take {take} of {max_takes} · quick if we've mixed this pair before")
    return e


def now_playing_embed(*, name: str, beat: str, vocals: str, style: str, take: int,
                      max_takes: int, total_secs: float, user: discord.abc.User | None,
                      in_voice: bool = False) -> discord.Embed:
    """The finished-mix card — Rythm 'Now playing' shape, in Electric Violet."""
    e = discord.Embed(
        title=f"🎛️  {name}",
        description=f"{bar(0, total_secs)}\n\n**{beat}** · beat   ✕   **{vocals}** · vocals",
        color=ACCENT)
    e.set_author(name="Now playing in voice 🔊" if in_voice else "Now playing 🎧")
    e.add_field(name="Style", value=style, inline=True)
    e.add_field(name="Take", value=f"{take} / {max_takes}", inline=True)
    e.add_field(name="Length", value=mmss(total_secs), inline=True)
    e.set_footer(text=f"{BOT_NAME} · {_requester(user)} · 🔄 another take · 🔊 play in voice")
    return e


def set_lineup_embed(lines: str, length_secs: float, kept: int,
                     user: discord.abc.User | None) -> discord.Embed:
    e = discord.Embed(title="🎚️  Your DJ set", description=lines or "—", color=ACCENT)
    e.set_author(name="Now playing 🎧 · continuous set")
    e.add_field(name="Length", value=mmss(length_secs), inline=True)
    e.add_field(name="Mixes", value=str(kept), inline=True)
    e.set_footer(text=f"{BOT_NAME} · {_requester(user)} · joined on the beat")
    return e


def building_embed(lines: str, count: int) -> discord.Embed:
    e = discord.Embed(
        title="Building your set…",
        description=f"{count} mixes, joined on the beat:\n{lines}\n\n`▚▚▚▚▚▚▚▚▚▚`  rendering…",
        color=ACCENT)
    e.set_author(name=f"{BOT_NAME} · building set")
    e.set_footer(text="Give it a minute or two the first time")
    return e


def error_embed(msg: str) -> discord.Embed:
    e = discord.Embed(title="Couldn't make that", description=msg, color=FAIL)
    e.set_author(name=f"{BOT_NAME} · hmm")
    return e


def help_embed() -> discord.Embed:
    """Rythm-style instructions so a first-timer knows exactly what to do."""
    e = discord.Embed(
        title=f"🎧  {BOT_NAME} — how it works",
        description=("Make a **DJ mashup** from two songs in your library — one song's **beat**, "
                     "the other's **vocals** — then play it right here or out loud in a voice channel."),
        color=ACCENT)
    e.add_field(
        name="🎛️  /mix",
        value=("Pick a **beat** and a **vocal** (start typing — it autocompletes) and Grinder posts "
               "the finished mix as a playable clip with buttons."),
        inline=False)
    e.add_field(
        name="🎚️  /set",
        value=("Build a continuous **back-to-back set** of 2–5 mixes, step by step, joined on the beat."),
        inline=False)
    e.add_field(
        name="🎵  /songs",
        value="See every song you can pick, split into **beats** and **vocals**.",
        inline=False)
    e.add_field(
        name="🔊  Playing out loud",
        value=("Join a voice channel, then tap **Play in voice** on any mix — Grinder joins and plays "
               "it like a music bot. Tap **Leave voice** when you're done."),
        inline=False)
    e.set_footer(text=f"{BOT_NAME} · a Prompt-DJ demo · your two songs, mixed like a DJ")
    return e
