"""Grinder's cards.

Pure builders (no network, no Discord state) so they're unit-testable. Every user-facing message
routes through here, so the look is consistent and the colour lives in ONE place. Colours come from
`brand.py`, sampled from the Grinder artwork itself.

THE RULE THAT SHAPES EVERY CARD IN THIS FILE (founder, 2026-08-11):
**Grinder never evaluates, rates, judges or predicts a grind.** Not in words, not in emoji, not in
colour, not in a score, not in a progress bar, not implied by ordering. A card shows what went in
and what came out. The user decides by listening.

Two reasons, and the second is the one that matters: an opinion printed on the card tells people
what to think before they hear it; and it CONTAMINATES the reaction data, which is the actual
product signal. If a card says "rough", people press 💀 because they were told to.

So: no flavour line, no verdict, no quality wording, and no technical readout either - no tempo,
no key, no Camelot, no mixing style, no take number. Song names, length, and who made it. That is
the whole vocabulary of a card.
"""
from __future__ import annotations

import wave
from pathlib import Path

import discord

import brand

ACCENT = brand.PRIMARY
FAIL = brand.FAIL
BOT_NAME = "Grinder"

# The reactions that carry the preference signal. Deliberately REACTIONS, not buttons: a Discord
# view stops responding after its timeout, so buttons would go dead on yesterday's grinds, while a
# reaction keeps working forever and survives a bot restart. See `on_raw_reaction_add` in bot.py.
REACTIONS = ("🔥", "💀", "😐")

_avatar_url: str | None = None


def set_avatar_url(url: str | None) -> None:
    """Remember the bot's avatar URL so cards can show it as their author icon."""
    global _avatar_url
    _avatar_url = url


def _author(e: discord.Embed, name: str) -> discord.Embed:
    if _avatar_url:
        e.set_author(name=name, icon_url=_avatar_url)
    else:
        e.set_author(name=name)
    return e


_FILL, _KNOB, _EMPTY = "━", "🔘", "─"


def mmss(seconds: float | int | None) -> str:
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


def bar(elapsed: float, total: float, width: int = 18) -> str:
    total = max(float(total or 0), 0.0)
    elapsed = min(max(float(elapsed or 0), 0.0), total) if total else 0.0
    pos = int((elapsed / total) * (width - 1)) if total else 0
    track = _FILL * pos + _KNOB + _EMPTY * (width - 1 - pos)
    return f"{track}  `{mmss(elapsed)} / {mmss(total)}`"


def wav_duration(path: str | Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            fr = w.getframerate()
            return w.getnframes() / fr if fr else 0.0
    except Exception:  # noqa: BLE001 - a duration read must never break a message
        return 0.0


def _who(user: discord.abc.User | None) -> str:
    return getattr(user, "display_name", None) or getattr(user, "name", None) or "someone"


def _mention(user: discord.abc.User | None) -> str:
    uid = getattr(user, "id", None)
    return f"<@{uid}>" if uid else _who(user)


# --------------------------------------------------------------------------------------
# State 1 - posted the instant somebody submits, before any rendering happens.
# --------------------------------------------------------------------------------------
def submit_embed(*, user: discord.abc.User | None, beat: str, vocals: str) -> discord.Embed:
    """Who threw what in. No prediction about how it will turn out - that is the point of the
    whole product, and the card must not spoil the guess."""
    e = discord.Embed(
        description=(f"{_mention(user)} just threw two things in the grinder\n\n"
                     f"🥁  **{beat}**\n"
                     f"🎤  **{vocals}**\n\n"
                     f"grinding..."),
        color=ACCENT)
    _author(e, f"{BOT_NAME}")
    return e


# --------------------------------------------------------------------------------------
# State 2 - the finished grind.
# --------------------------------------------------------------------------------------
def grind_embed(*, number: int, user: discord.abc.User | None, pairs: list[tuple[str, str]],
                total_secs: float,
                booth_listeners: int | None = None, room_name: str | None = None,
                queued_behind: int = 0, voice_failed: bool = False) -> discord.Embed:
    """One card for both shapes. A single pair reads as one line; two or more become a long grind
    with a numbered running order.

    There is no "just landed" marker any more, because nothing lands after the fact: every pair is
    chosen up front and the whole set arrives at once."""
    long_grind = len(pairs) > 1
    title = f"GRIND #{number}  ·  by {_who(user)}"
    if long_grind:
        title += f"  ·  long grind  ·  {len(pairs)} tracks"

    if long_grind:
        body = "\n".join(f"`{i}`  **{beat}**  ✕  **{vocals}**"
                         for i, (beat, vocals) in enumerate(pairs, start=1))
    else:
        beat, vocals = pairs[0]
        body = f"**{beat}**  ✕  **{vocals}**"

    if voice_failed:
        # Not a judgement of the grind, which is fine and attached above. Only the out-loud part
        # failed, and saying so beats a card implying a room heard something it did not.
        body = f"🔇  couldn't play it out loud, the clip above still works\n\n{body}"
    elif booth_listeners is not None:
        listening = "1 listening" if booth_listeners == 1 else f"{booth_listeners} listening"
        where = f"IN {room_name.upper()}" if room_name else "IN VOICE"
        body = f"🔊  **PLAYING LIVE {where}**  ·  {listening}\n\n{body}"
    elif queued_behind > 0:
        # A statement of position, not a judgement. A bot can hold only one voice connection per
        # server, so a grind finishing while another is playing waits rather than interrupting.
        nxt = "next up" if queued_behind == 1 else f"{queued_behind} ahead of it"
        body = f"🔊  waiting for the room  ·  {nxt}\n\n{body}"

    e = discord.Embed(title=f"🎧  {title}", description=body, color=ACCENT)
    _author(e, BOT_NAME)
    if total_secs:
        e.add_field(name="Length", value=mmss(total_secs), inline=True)
    return e


def error_embed(msg: str) -> discord.Embed:
    e = discord.Embed(title="That did not come out", description=msg, color=FAIL)
    _author(e, f"{BOT_NAME} · hmm")
    return e


# --------------------------------------------------------------------------------------
# The Booth's live status - one pinned message the bot keeps editing.
# --------------------------------------------------------------------------------------
def booth_live_embed(*, listeners: int, grinds_this_session: int,
                     last_up: str | None, room: str | None = None) -> discord.Embed:
    people = "1 person in" if listeners == 1 else f"{listeners} people in"
    where = f" **{room}**" if room else " the rooms"
    made = ("nothing yet" if grinds_this_session == 0 else
            "1 grind this session" if grinds_this_session == 1 else
            f"{grinds_this_session} grinds this session")
    body = f"{people}{where}  ·  {made}"
    if last_up:
        body += f"\nlast up: {last_up}"
    body += "\n\n→ jump in and grind something, everyone in there hears it"
    return discord.Embed(title="🔴  SOMEONE IS LISTENING", description=body, color=ACCENT)


def booth_quiet_embed() -> discord.Embed:
    return discord.Embed(
        title="⚫  Nobody is listening right now.",
        description="Somebody go start something.",
        color=brand.DEEP)


def arrival_line(name: str, room: str, listeners: int) -> str:
    people = "1 in there" if listeners == 1 else f"{listeners} in there"
    return f"🚪 **{name}** walked into **{room}**. {people}."


# --------------------------------------------------------------------------------------
# /mygrinds and /help
# --------------------------------------------------------------------------------------
def mygrinds_embed(*, user: discord.abc.User | None, total: int,
                   rows: list[tuple[int, str, str | None]]) -> discord.Embed:
    """rows: (number, "beat x vocal" or "long grind, N tracks", jump_url)"""
    if not rows:
        body = "You have not ground anything yet.\n\nGo to #the-grinder and type `/grind`."
    else:
        body = "\n".join(
            f"`#{n}`  {label}" + (f"  ·  [jump]({url})" if url else "")
            for n, label, url in rows)
    e = discord.Embed(title=f"🎛️  {_who(user)}'s grinds", description=body, color=ACCENT)
    _author(e, BOT_NAME)
    made = "1 grind" if total == 1 else f"{total} grinds"
    e.set_footer(text=f"{made} all time")
    return e


def help_embed() -> discord.Embed:
    e = discord.Embed(
        title=f"🎧  {BOT_NAME}",
        description=("Grinder mashes two songs together. You pick a **beat**. You pick a **vocal**. "
                     "It works out how to make them one track.\n\n"
                     "Sometimes it is incredible. Sometimes it is a war crime. That is the fun part."),
        color=ACCENT)
    e.set_thumbnail(url="attachment://logo.png")
    e.add_field(
        name="⚙️  /grind",
        # No option form here on purpose: /grind takes no arguments. It used to, and this line
        # outlived the change, so /help was teaching a shortcut that silently does nothing.
        value=("Type it and a picker opens: choose a beat, choose a vocal, and hit "
               "**➕ Add another** to stack up to 5 pairs. Then **Grind it** and the whole lot "
               "comes back as one continuous set."),
        inline=False)
    e.add_field(
        name="🔁  Again",
        value=("Same songs, mixed differently. The line-up stays exactly as you built it."),
        inline=False)
    e.add_field(
        name="🔥 💀 😐",
        value="React to grinds. Yours and everyone else's. That is how the good ones get found.",
        inline=False)
    e.add_field(
        name="🎛️  /mygrinds",
        value="Everything you have made.",
        inline=False)
    e.add_field(
        name="🔊  The Booth",
        value=("Grind while you are sitting in The Booth and it plays out loud to everyone in "
               "there. Ten people finding out together is a better time than doing it alone."),
        inline=False)
    e.set_footer(text=f"{BOT_NAME} · go break something")
    return e
