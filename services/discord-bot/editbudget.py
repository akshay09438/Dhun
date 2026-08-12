"""A shared edit budget, so ten moving cards in one channel do not shout over each other.

THE PROBLEM, found by tracing the ten-people case on 2026-08-12.

Every grind gets a card that updates as the engine works, and each card is already polite on its
own: `_on_progress` only edits when the line actually CHANGES, so a grind sitting in one stage for
twenty seconds costs exactly one edit.

But politeness per card is not politeness per channel. Discord rate-limits message edits **per
channel**, and the cards had no knowledge of each other at all - no shared counter, no
coordination of any kind. Ten people grinding in `#get-shit-done` means ten cards changing stage
independently in one channel, which is precisely the case nobody had run.

WHAT GOES WRONG, AND WHAT DOES NOT. Being hit by the rate limiter does not lose anybody's mix -
the audio still arrives and still attaches. It makes discord.py stall on the limiter, so cards
freeze and update late, and the whole channel's edits queue behind each other. It degrades; it
does not break. Worth knowing before panicking at a party.

THE FIX IS TO DROP, NOT TO QUEUE. When the budget is spent, a progress edit is SKIPPED rather than
delayed. A queued progress edit would arrive carrying information that is already stale - the next
tick is two seconds away and knows more. Dropping is strictly better than delaying here.

WHAT IS NEVER DROPPED: the final edit that delivers the finished mix, and the failure message.
Those are the only edits that carry something a person actually needs, so they bypass the budget
entirely and are allowed to wait on the limiter if they must.
"""
from __future__ import annotations

import time

# Discord's published allowance for editing messages is about 5 per 5 seconds per channel. Sit
# deliberately under it: the spare slot is headroom for the edits that bypass this budget (a
# finished mix, a failure) and for anything else posting in the channel.
DEFAULT_EDITS = 4
DEFAULT_WINDOW_SECS = 5.0


class EditBudget:
    """A tiny per-channel token bucket. Not thread-safe by design - discord.py runs everything on
    one event loop, and adding a lock here would imply a concurrency that does not exist."""

    def __init__(self, edits: int = DEFAULT_EDITS, window_secs: float = DEFAULT_WINDOW_SECS,
                 clock=time.monotonic) -> None:
        self.edits = edits
        self.window_secs = window_secs
        self._clock = clock
        self._spent: dict[int, list[float]] = {}

    def allow(self, channel_id: int) -> bool:
        """True if a *droppable* edit may go out in this channel right now.

        Records the spend when it returns True, so callers must only ask when they intend to edit.
        """
        now = self._clock()
        cutoff = now - self.window_secs
        recent = [t for t in self._spent.get(channel_id, ()) if t > cutoff]
        if len(recent) >= self.edits:
            self._spent[channel_id] = recent
            return False
        recent.append(now)
        self._spent[channel_id] = recent
        return True

    def spent_in(self, channel_id: int) -> int:
        """How many edits this channel has used in the current window. For tests and logging."""
        cutoff = self._clock() - self.window_secs
        return len([t for t in self._spent.get(channel_id, ()) if t > cutoff])

    def forget(self, channel_id: int) -> None:
        self._spent.pop(channel_id, None)


# One budget for the whole bot. A module-level singleton rather than something passed around,
# because the whole point is that cards which know nothing about each other still share it.
budget = EditBudget()
