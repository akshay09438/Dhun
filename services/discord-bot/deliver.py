"""Handing a finished mix to the person who made it - somewhere Discord actually keeps it.

THE BUG THIS EXISTS FOR, proven against Discord on 2026-08-16. A grind card is an ephemeral
message. Discord shows one of those once, to one person, and stores it NOWHERE - asking Discord
for the two cards Aashwin lost, by id, returns "not found" for both. The bot had done everything
right: rendered, transcoded, attached, edited the card. He closed the app and his music ceased to
exist. 38 of the 39 grinds ever made were in that position.

`/mygrinds` can fetch a mix back, and that stays. But recovery asks somebody to know a command and
think to use it at the exact moment they have decided the product lost their work. The founder's
call, 2026-08-16: "the song has to be sent to the user by hook or by crook - I don't want users to
go to /mygrinds and find their last song."

WHY A DIRECT MESSAGE. It is exactly as private as an ephemeral card - nobody else can see it, which
is the whole reason grinds went private - and Discord keeps it forever, on every device that person
owns. Privacy was never the thing that made a card disappear; being ephemeral was.

BOTH ROUTES, NOT ONE. The card keeps its copy as well. The card is where they are looking in the
moment; the DM is the copy still there next month. Moving the mix out of the card would trade one
loss for another.

BY HOOK OR BY CROOK, honestly:
  * a transient failure is retried - one Discord hiccup must not cost somebody their song;
  * DMs switched off is permanent, so it is NOT retried. It is explained on the card, naming the
    one thing they can change, because a silent failure here is indistinguishable from the bug;
  * nothing in here may ever raise. A mix that rendered must never be lost in the act of being
    handed over.
"""
from __future__ import annotations

import logging

import discord

log = logging.getLogger("promptdj.discord")

# One retry. Two attempts covers a Discord hiccup; more would just make somebody wait longer for
# an answer that is not coming, and `/mygrinds` is already the floor under all of this.
_ATTEMPTS = 2

_SENT = "📩  Also sent to your messages, so this one is yours to keep."

_DMS_OFF = (
    "I could not send you a copy - your Discord is set to refuse direct messages from people in "
    "this server. **This card disappears when you reload Discord**, so turn those on and every "
    "mix will be waiting in your messages. `/mygrinds` can always fetch one back."
)

_TOO_BIG = (
    "This one is too long to send you a copy - Discord will not take a file that big. It is not "
    "lost: `/mygrinds` will fetch it, and a listening room can play it."
)

_NO_LUCK = (
    "I could not get a copy into your messages just now. `/mygrinds` will fetch it whenever you "
    "want it."
)


async def to_the_maker(user, number: int, wav, attach) -> tuple[bool, str]:
    """Send the finished mix to `user` privately. Returns (delivered, a line for the card).

    `attach` builds a fresh Discord file from the wav. It is called again for a retry because a
    `discord.File` is consumed by the send that fails - reusing one would retry with an exhausted
    handle and fail for a second, invented reason.
    """
    clip = await attach(wav)
    if clip is None:
        return False, _TOO_BIG

    for attempt in range(_ATTEMPTS):
        try:
            if attempt:
                clip = await attach(wav)
                if clip is None:
                    return False, _TOO_BIG
            channel = getattr(user, "dm_channel", None) or await user.create_dm()
            await channel.send(content=f"Grind #{number}", file=clip)
            return True, _SENT
        except discord.Forbidden:
            # Permanent. Retrying a closed door just makes them wait for the same answer.
            log.info("grind #%s: DMs are closed for %s", number, getattr(user, "id", "?"))
            return False, _DMS_OFF
        except Exception:  # noqa: BLE001 - see the module docstring: delivery never raises
            log.warning("grind #%s: could not DM the mix (attempt %d/%d)",
                        number, attempt + 1, _ATTEMPTS, exc_info=True)

    return False, _NO_LUCK
