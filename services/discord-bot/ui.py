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
def _about_how_long(secs: int | None) -> str:
    """A wait, in words a person reads rather than a number they have to convert. Deliberately
    vague, because it IS vague - a false precision like '2m41s' reads as a promise."""
    if not secs or secs <= 0:
        return ""
    if secs < 60:
        return "under a minute"
    return f"about {round(secs / 60)} min"


def waiting_line(*, stage: str | None = None, position: int | None = None,
                 eta_secs: int | None = None) -> str:
    """The one line on the card that MOVES while a grind is being made.

    Why this exists: the card used to say "grinding..." and then not change for 25-30 seconds
    (longer behind a queue). A first-timer reads a frozen card as a broken bot and gives up -
    which costs more users than any actual failure does. So it always says something true about
    right now, and never invents progress it cannot see."""
    if position:
        wait = _about_how_long(eta_secs)
        place = f"⏳  {position} ahead of you in the line"
        return f"{place}  ·  {wait}" if wait else place
    if stage:
        return f"⚙️  {stage}"
    return "grinding..."


def submit_embed(*, user: discord.abc.User | None, beat: str, vocals: str,
                 stage: str | None = None, position: int | None = None,
                 eta_secs: int | None = None) -> discord.Embed:
    """Who threw what in. No prediction about how it will turn out - that is the point of the
    whole product, and the card must not spoil the guess.

    The last line is live: it is re-rendered as the grind moves through the line and through the
    engine's own stages, so the card is never motionless for half a minute."""
    e = discord.Embed(
        description=(f"{_mention(user)} just threw two things in the grinder\n\n"
                     f"🥁  **{beat}**\n"
                     f"🎤  **{vocals}**\n\n"
                     f"{waiting_line(stage=stage, position=position, eta_secs=eta_secs)}"),
        color=ACCENT)
    _author(e, f"{BOT_NAME}")
    return e


# --------------------------------------------------------------------------------------
# State 2 - the finished grind.
# --------------------------------------------------------------------------------------
def grind_embed(*, number: int, user: discord.abc.User | None, pairs: list[tuple[str, str]],
                total_secs: float,
                booth_listeners: int | None = None, room_name: str | None = None,
                queued_behind: int = 0, voice_failed: bool = False,
                waiting_for_voice: bool = False) -> discord.Embed:
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
        # A statement of position, not a judgement. Two different reasons to wait, and telling them
        # apart matters: "the room is busy" is a queue you are in, and "every voice is busy" is a
        # limit on how many rooms can have sound at once. Somebody staring at "grinding..." with no
        # explanation assumes it broke and presses the button again, which genuinely makes it worse.
        nxt = "next up" if queued_behind == 1 else f"{queued_behind} ahead of it"
        why = "waiting for a free voice" if waiting_for_voice else "waiting for the room"
        body = f"🔊  {why}  ·  {nxt}\n\n{body}"

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


def board_embed(*, live: int, made_today: int, people_today: int) -> discord.Embed:
    """The one standing line in the grind room.

    Grinds are private now, so this is the only thing in there saying anybody is around. Two rules
    it lives by, both learned from the card that had to be deleted:

    * NEVER ANNOUNCE AN EMPTY ROOM. Nobody is mid-grind most of the time - a grind takes under a
      minute - so a live-count-only line would read "0" nearly always, which is the dead room with
      extra steps. With nobody grinding it shows what the room has MADE, which is true, and is the
      social proof that private grinds took away.
    * NEVER JUDGE. No "great", no "best", no score. A board that rated anything would tell people
      what to think before they listen, and poison the reactions.
    """
    if live == 1:
        head = "**1 person is grinding right now**"
    elif live > 1:
        head = f"**{live} people are grinding right now**"
    elif made_today == 0:
        head = "**Nothing made here yet today**"
    elif made_today == 1:
        head = "**1 mix made here today**"
    else:
        who = "1 person" if people_today == 1 else f"{people_today} people"
        head = f"**{made_today} mixes made here today**, by {who}"
    body = f"{head}\n\n→ `/grind` — pick two songs, it comes back to you"
    return discord.Embed(title="🎧  THE GRINDER", description=body, color=ACCENT)


# `booth_quiet_embed` ("⚫ Nobody is listening right now. Somebody go start something.") was here
# and is DELETED (founder decision 2026-08-13). A quiet room now shows nothing at all: the live
# sign is taken down instead of being swapped for a card announcing that nothing is happening.


# `arrival_line` was here and is DELETED, not disabled (founder decision 2026-08-13). Nothing
# announces somebody walking into a listening room any more - Discord's member list already shows
# who is in there. See the note at the top of booth.py for why the throttle did not save it.


# --------------------------------------------------------------------------------------
# /mygrinds and /help
# --------------------------------------------------------------------------------------
def mygrinds_embed(*, user: discord.abc.User | None, total: int,
                   rows: list[tuple[int, str, str | None]]) -> discord.Embed:
    """rows: (number, "beat x vocal" or "long grind, N tracks", jump_url)"""
    if not rows:
        # NO TYPED CHANNEL NAME. `the-grinder` has been `get-shit-done` on the live server for
        # days, so this sent every brand-new person to a room that does not exist.
        body = "You have not ground anything yet.\n\nType `/grind` in the grind room."
    else:
        body = "\n".join(
            f"`#{n}`  {label}" + (f"  ·  [jump]({url})" if url else "")
            for n, label, url in rows)
    e = discord.Embed(title=f"🎛️  {_who(user)}'s grinds", description=body, color=ACCENT)
    _author(e, BOT_NAME)
    made = "1 grind" if total == 1 else f"{total} grinds"
    e.set_footer(text=f"{made} all time")
    return e


def help_embed(rooms: list | None = None, banner_name: str | None = None) -> discord.Embed:
    """What Grinder does, in the fewest fields that still answer a newcomer.

    TWO THINGS THIS GOT WRONG BEFORE (fixed 2026-08-12, founder-reported):

    1. It talked about "The Booth" - a single voice channel that has not existed since the rooms
       were split into Bollywood_House and Hollywood_Blends. `rooms` is passed in so the real
       rooms appear as LIVE CHANNEL LINKS that follow a rename, rather than as typed names that
       rot the moment the founder renames something. This is the same failure mode that left
       #read-this-first advertising three deleted commands for two versions.
    2. It never mentioned the listening-room controls, so nobody could discover them.

    Kept deliberately short. The previous version had six fields and read as a wall.
    """
    e = discord.Embed(
        title=f"🎧  {BOT_NAME}",
        description=("Grinder mashes two songs together. You pick a **beat**. You pick a **vocal**. "
                     "It works out how to make them one track.\n\n"
                     "Sometimes it is incredible. Sometimes it is a war crime. That is the fun part."),
        color=ACCENT)
    if banner_name:
        e.set_image(url=f"attachment://{banner_name}")
    e.add_field(
        name="⚙️  /grind",
        # No option form here on purpose: /grind takes no arguments. It used to, and this line
        # outlived the change, so /help was teaching a shortcut that silently does nothing.
        value=("Type it and a picker opens: pick a beat, pick a vocal, hit **➕ Add another** to "
               "stack up to 5 pairs, then **Grind it**.\n"
               "🔁 **Again** remixes the same songs differently. 🎛️ **/mygrinds** is everything "
               "you have made - pick one there to get the file back."),
        inline=False)
    e.add_field(
        name="🔥 💀 😐",
        # Your grind comes back only to you, so there is nothing for anybody else to react TO until
        # you share it. The old line ("yours and everyone else's") described the public-cards
        # version of the room and outlived it by a day.
        value=("Your grinds are private. Press 📣 **Show this mix to everyone** to put one up "
               "where the room can hear it - and react to."),
        inline=False)

    where = _room_links(rooms) or "a listening room"
    e.add_field(
        name="🔊  Listening rooms",
        # NO "the room keeps playing past grinds by itself" - that station was removed on
        # 2026-08-12 ("a room that starts playing things nobody requested is chaos, not company").
        # The line survived the removal and promised a behaviour that had been deleted.
        value=(f"Sit in {where} and the music plays out loud to everyone in there. "
               "Grind while you are in one and everybody hears it at the same second."),
        inline=False)
    e.add_field(
        name="⏭️  While the music is on",
        value=("**/skip** - next track\n"
               "**/stop** - pause it\n"
               "**/play** - start it up, or pick up where you stopped\n"
               "_Anyone in the room can use these._"),
        inline=False)
    e.set_footer(text=f"{BOT_NAME} · go break something")
    return e


def _room_links(rooms: list | None) -> str:
    """Real channel mentions, so a renamed room keeps working. Never typed names."""
    if not rooms:
        return ""
    links = [f"<#{getattr(r, 'id', 0)}>" for r in rooms if getattr(r, "id", None)]
    if not links:
        return ""
    if len(links) == 1:
        return links[0]
    return " or ".join([", ".join(links[:-1]), links[-1]])
