"""One line in the grind room that says the place is alive.

Grinds went private on 2026-08-15 (founder's call, and it solved the overwhelm) - but it left
`#get-shit-done` with nothing in it at all, and this project's own door design says an empty room is
the worst thing that can happen to a new community. So: a single board, kept up to date, saying how
many people are grinding right now and what the room has made today.

TWO THINGS IT MUST GET RIGHT, both learned the hard way and both written into booth.py:

1. IT MUST SURVIVE A RESTART. The "⚫ Nobody is listening right now" card was meant to be ONE
   message edited in place, but its handle lived only in memory - so every restart lost it and
   posted a fresh one, and the founder's channel filled with a column of identical grey cards. It
   was deleted rather than fixed. This board keeps its message id in the DATABASE, so a new process
   finds the same message and edits it. If that message is genuinely gone (somebody deleted it) it
   posts one replacement and remembers that instead - never editing into the void.

2. IT MUST NOT NAG. The same card was judged "nagging, not information" for announcing an empty
   room. Nobody is mid-grind most of the time - a grind lasts under a minute - so a live-count-only
   board would read "0" almost always, which is the same dead room with extra steps. When nobody is
   grinding this says what the room has MADE today: the social proof that private grinds removed,
   without putting anybody's music back on the wall.

And the standing rule applies here as everywhere: **Grinder never judges a mix.** No "great", no
"best", no score - a board that ranked anything would prejudice the reactions, which are the signal
the whole product is being built to read.
"""
from __future__ import annotations

import logging
import time

import store
import ui

log = logging.getLogger("promptdj.discord")

# At most one edit per burst. A start and a finish seconds apart must not cost two edits against
# Discord's per-channel budget - the same budget the grind cards already share.
_MIN_SECONDS_BETWEEN_EDITS = 5.0

_live: set[int] = set()          # who is mid-grind RIGHT NOW; in memory on purpose - a restart
                                 # means nothing is in flight, so an empty set is the truth
_last_edit: dict[int, float] = {}


def reset_for_tests() -> None:
    """Forget everything held in memory. Stands in for a restart."""
    _live.clear()
    _last_edit.clear()


def started(user_id: int) -> None:
    _live.add(user_id)


def finished(user_id: int) -> None:
    _live.discard(user_id)


def live_count() -> int:
    return len(_live)


async def channel_for(client, channel_id: int | None):
    """The channel to put the board in, from the cache OR by asking Discord.

    OBSERVED, not theorised: on one restart (2026-08-15 20:29) `get_channel` returned None at
    `on_ready` and the board silently never appeared; the very next restart it worked. The cache is
    filled from gateway events and is simply not guaranteed to be ready at that moment. A cache miss
    now falls back to a real fetch, so a startup board cannot depend on a race."""
    if not channel_id:
        return None
    cached = client.get_channel(channel_id)
    if cached is not None:
        return cached
    try:
        return await client.fetch_channel(channel_id)
    except Exception:  # noqa: BLE001 - deleted, or not visible to this bot
        log.warning("board: channel %s is not reachable", channel_id, exc_info=True)
        return None


async def refresh(channel) -> None:
    """Bring the board up to date. Best-effort: a board that fails to update is a cosmetic loss and
    must never take a grind down with it."""
    if channel is None:
        # SAY SO. A sign that silently does nothing is the hardest kind of thing to notice is
        # broken - this project has already lost an evening to a bot that wrote no log.
        log.warning("board: no channel to post in (is the grind channel configured, and can "
                    "Grinder see it?)")
        return
    now = time.monotonic()
    last = _last_edit.get(getattr(channel, "id", 0))
    if last is not None and now - last < _MIN_SECONDS_BETWEEN_EDITS:
        return
    try:
        made, people = store.counts_today()
        embed = ui.board_embed(live=live_count(), made_today=made, people_today=people)
        message = await _existing(channel)
        if message is None:
            posted = await channel.send(embed=embed)
            store.set_board_message(channel.id, posted.id)
            log.info("board: posted a new one in %s (live=%d, today=%d)",
                     getattr(channel, "name", channel.id), live_count(), made)
        else:
            await message.edit(embed=embed)
            log.info("board: updated (live=%d, today=%d)", live_count(), made)
        _last_edit[channel.id] = now
    except Exception:  # noqa: BLE001 - never let the sign break somebody's grind
        log.warning("board: could not update the grind board", exc_info=True)


async def _existing(channel):
    """The board this channel already has, or None if there isn't one any more.

    The id comes from the database rather than memory, which is the whole point: a restart must
    edit the board it already posted instead of adding another one."""
    mid = store.board_message(channel.id)
    if not mid:
        return None
    try:
        return await channel.fetch_message(mid)
    except Exception:  # noqa: BLE001 - deleted by hand, or from a server we no longer see
        store.set_board_message(channel.id, None)
        return None
