"""How many PAID upload attempts have been made, ever. The real defence against a runaway bill.

WHY THIS EXISTS, and why it is not the per-person cap. The 2026-08-17 re-review measured one
uploader driving **12 paid stem separations for $1.44 with zero songs kept and zero quota used** —
because a failed attempt releases its slot (the founder's rule: a Replicate outage must not burn
somebody's five) and a failure writes no catalogue row. So the per-person cap bounds how many songs
you can KEEP. It has never bounded money, and those were never the same thing.

This does. Every attempt that is about to reach Replicate increments this counter, success or
failure, for everybody together. At the ceiling `/add` refuses for everyone with a plain sentence
until the founder raises it.

DURABLE ON PURPOSE. Reservations live in memory because a restart kills the threads they track;
spend is the opposite — money already sent to Replicate is not undone by a restart, so this is a
file. Written with the same atomic temp-then-replace as the catalogue index, because a torn write
here would either lose the record of real spending or corrupt it into refusing everybody.

It only ever goes UP. There is no decrement: a refund path would be a way to spend twice.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from app.config import settings

log = logging.getLogger("promptdj.spend")

_LOCK = threading.RLock()


class BudgetSpent(Exception):
    """The shared paid-attempt budget is used up — carries the sentence to show a person."""


def _path() -> Path:
    return settings.data_dir / "upload_spend.json"


def attempts() -> int:
    """Paid attempts recorded so far. Unreadable file reads as the CEILING, not as zero.

    Failing to the ceiling is deliberate: if we cannot tell how much has been spent, refusing is
    recoverable (the founder raises the number) and guessing zero is not (the balance is gone).
    """
    p = _path()
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("paid_attempts", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        log.exception("could not read the upload spend record; treating the budget as SPENT")
        return settings.max_paid_upload_attempts


def remaining() -> int:
    return max(0, settings.max_paid_upload_attempts - attempts())


def record_attempt(song_id: str, uploader: str) -> int:
    """Count one attempt that is about to cost money. Returns the new total.

    Called BEFORE the Replicate call, never after — an attempt that dies mid-call has still been
    paid for, and counting it afterwards would miss exactly the failures this exists to bound.
    """
    with _LOCK:
        n = attempts() + 1
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=".spend-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"paid_attempts": n, "last_song": song_id, "last_by": uploader}, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        log.info("paid upload attempt %d of %d (song %s by %s)",
                 n, settings.max_paid_upload_attempts, song_id[:12], uploader)
        return n


def check_budget() -> None:
    """Raise BudgetSpent if there is no room for another paid attempt."""
    if remaining() <= 0:
        raise BudgetSpent(
            "Adding songs is paused — the shared budget for processing new songs is used up. "
            "Nothing is lost and nothing is broken; it needs topping up before more can go in.")
